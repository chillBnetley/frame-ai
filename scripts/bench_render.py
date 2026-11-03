#!/usr/bin/env python3
"""Measure Phase 2 render/export latency and export peak RSS against section 7.8."""

from __future__ import annotations

import argparse
import gc
import math
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Self, TypeVar

import httpx
import numpy as np
import PIL
import psutil
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "services" / "api"
EXPORT_QUALITY = 92
TEMP_UPLOAD_BYTES = int(19.5 * 1024 * 1024)
T = TypeVar("T")


@dataclass(frozen=True)
class Source:
    name: str
    width: int
    height: int


SOURCES = {
    "1mp": Source("1 MP", 1000, 1000),
    "6mp": Source("6 MP", 3000, 2000),
    "12mp": Source("12 MP", 4000, 3000),
    "24mp": Source("24 MP", 6000, 4000),
    "40mp": Source("40 MP", 7296, 5472),
}


def git(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except OSError as exc:
        return f"(git unavailable: {exc})"
    return result.stdout.strip() or "(empty)"


def make_image(
    source: Source, seed: int = 20261102, noisy: bool = False
) -> Image.Image:
    width, height = source.width, source.height
    if noisy:
        rng = np.random.default_rng(seed)
        pixels = rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)
        return Image.fromarray(pixels, mode="RGB")

    pixels = np.empty((height, width, 3), dtype=np.uint8)
    x = np.linspace(0.0, 1.0, width, dtype=np.float32)
    y = np.linspace(0.0, 1.0, height, dtype=np.float32)
    pixels[:, :, 0] = np.clip(30.0 + 190.0 * x, 0, 255)[None, :]
    pixels[:, :, 1] = np.clip(40.0 + 160.0 * y, 0, 255)[:, None]
    pixels[:, :, 2] = np.clip(70.0 + 120.0 * (1.0 - y), 0, 255)[:, None]

    stripes = (np.sin(np.arange(width, dtype=np.float32) * 0.06) * 18.0).astype(
        np.int16
    )
    pixels[:, :, 1] = np.clip(
        pixels[:, :, 1].astype(np.int16) + stripes[None, :], 0, 255
    ).astype(np.uint8)

    step = max(24, min(width, height) // 30)
    pixels[::step, :, :] = np.clip(pixels[::step, :, :].astype(np.int16) * 0.8, 0, 255)
    pixels[:, ::step, :] = np.clip(pixels[:, ::step, :].astype(np.int16) * 0.8, 0, 255)

    for index in range(8):
        top = max(0, height // 8 + index * max(8, height // 20))
        left = max(0, width // 10 + index * max(8, width // 18))
        bottom = min(height, top + max(8, height // 24))
        right = min(width, left + max(8, width // 10))
        pixels[top:bottom, left:right, 0] = 235 - index * 16
        pixels[top:bottom, left:right, 1] = 55 + index * 20
        pixels[top:bottom, left:right, 2] = 45 + index * 12
    return Image.fromarray(pixels, mode="RGB")


def save_jpeg(image: Image.Image, path: Path, quality: int) -> bytes:
    image.save(path, format="JPEG", quality=quality, subsampling=0)
    return path.read_bytes()


def recipe(
    *,
    exposure_ev: float = 0.0,
    contrast: float = 0.0,
    saturation: float = 0.0,
    denoise: float = 0.0,
) -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "styleId": "natural",
        "styleStrength": 0.0,
        "adjustments": {
            "exposureEv": round(exposure_ev, 2),
            "contrast": round(contrast, 2),
            "saturation": round(saturation, 2),
            "denoise": round(denoise, 2),
        },
        "rationale": [],
        "warnings": [],
    }


def full_recipe(*, denoise: float = 0.0) -> dict[str, object]:
    """Worst-case export recipe used to measure the real upper bound."""
    return {
        "schemaVersion": "1.0",
        "styleId": "natural",
        "styleStrength": 0.0,
        "adjustments": {
            "exposureEv": 0.35,
            "contrast": 12,
            "highlights": -20,
            "shadows": 25,
            "temperature": 8,
            "tint": -5,
            "saturation": 10,
            "vibrance": 15,
            "clarity": 10,
            "sharpen": 20,
            "denoise": round(denoise, 2),
            "vignette": -15,
            "grain": 8,
            "rotationDeg": 2,
        },
        "rationale": [],
        "warnings": [],
    }


class ApiServer:
    def __init__(self, base_url: str | None, api_pid: int | None) -> None:
        self.base_url = base_url
        self.api_pid = api_pid
        self.process: subprocess.Popen[bytes] | None = None
        self.data_dir: Path | None = None
        self.client: httpx.Client | None = None

    def __enter__(self) -> Self:
        if self.base_url is None:
            self.data_dir = Path(tempfile.mkdtemp(prefix="frame-ai-bench-"))
            port = _free_port()
            self.base_url = f"http://127.0.0.1:{port}"
            environment = {
                **os.environ,
                "FRAME_DATA_DIR": str(self.data_dir),
                "FRAME_LOG_LEVEL": "WARNING",
                "FRAME_PREVIEW_TTL_SECONDS": "86400",
                "PYTHONUNBUFFERED": "1",
            }
            self.process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--log-level",
                    "warning",
                ],
                cwd=API_DIR,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.api_pid = self.process.pid
        self.client = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(240.0, connect=15.0),
        )
        self._wait_ready()
        if self.api_pid is None:
            self.api_pid = _find_pid_for_port(int(self.base_url.rsplit(":", 1)[1]))
        return self

    def __exit__(self, *_exc: object) -> None:
        if self.client is not None:
            self.client.close()
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        if self.data_dir is not None:
            import shutil

            shutil.rmtree(self.data_dir, ignore_errors=True)

    def _wait_ready(self) -> None:
        assert self.client is not None
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError("API server exited before becoming ready")
            try:
                response = self.client.get("/api/v1/health")
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.25)
        raise RuntimeError("API server did not become ready in 90 seconds")


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _find_pid_for_port(port: int) -> int:
    for connection in psutil.net_connections(kind="tcp"):
        if (
            connection.status == psutil.CONN_LISTEN
            and connection.laddr
            and connection.laddr.port == port
        ):
            return int(connection.pid)
    raise RuntimeError(f"could not find the API process listening on port {port}")


def _expect(response: httpx.Response, expected: int) -> httpx.Response:
    if response.status_code != expected:
        raise RuntimeError(
            f"{response.request.method} {response.request.url} -> "
            f"{response.status_code}: {response.text[:500]}"
        )
    return response


def upload(client: httpx.Client, payload: bytes, filename: str) -> dict[str, object]:
    response = _expect(
        client.post(
            "/api/v1/images",
            files={"file": (filename, payload, "image/jpeg")},
        ),
        201,
    )
    return response.json()


def create_session(client: httpx.Client, image_id: str) -> dict[str, object]:
    return _expect(
        client.post("/api/v1/sessions", json={"imageId": image_id}), 201
    ).json()


def create_revision(
    client: httpx.Client,
    session_id: str,
    parent_revision_id: str,
    request_recipe: dict[str, object],
) -> dict[str, object]:
    return _expect(
        client.post(
            f"/api/v1/sessions/{session_id}/revisions",
            json={
                "recipe": request_recipe,
                "parentRevisionId": parent_revision_id,
                "source": "user",
            },
        ),
        201,
    ).json()


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def timed_render(
    client: httpx.Client,
    session_id: str,
    *,
    request_recipe: dict[str, object],
    quality: str,
    max_edge: int,
) -> float:
    started = time.perf_counter()
    response = _expect(
        client.post(
            f"/api/v1/sessions/{session_id}/render",
            json={"recipe": request_recipe, "quality": quality, "maxEdge": max_edge},
        ),
        200,
    )
    elapsed = (time.perf_counter() - started) * 1000
    payload = response.json()
    if payload.get("cacheHit"):
        raise RuntimeError("benchmark recipe unexpectedly hit the preview cache")
    return elapsed


def _tree_rss(process: psutil.Process) -> int:
    total = process.memory_info().rss
    try:
        children = process.children(recursive=True)
    except psutil.NoSuchProcess:
        return total
    for child in children:
        try:
            total += child.memory_info().rss
        except psutil.NoSuchProcess:
            continue
    return total


def sample_peak_rss(
    pid: int, operation: Callable[[], T]
) -> tuple[float, float, float, T]:
    process = psutil.Process(pid)
    samples = [_tree_rss(process)]
    stop = threading.Event()

    def sample() -> None:
        while not stop.wait(0.01):
            try:
                samples.append(_tree_rss(process))
            except psutil.NoSuchProcess:
                break

    thread = threading.Thread(target=sample, daemon=True)
    thread.start()
    started = time.perf_counter()
    result = operation()
    elapsed = (time.perf_counter() - started) * 1000
    stop.set()
    thread.join(timeout=2)
    return max(samples) / (1024 * 1024), samples[0] / (1024 * 1024), elapsed, result


def render_scenario(
    client: httpx.Client,
    source: Source,
    quality: str,
    max_edge: int,
    denoise: float,
    iterations: int,
) -> dict[str, object]:
    image = make_image(source)
    with tempfile.TemporaryDirectory(prefix="frame-ai-bench-image-") as directory:
        payload = save_jpeg(image, Path(directory) / "source.jpg", 86)
    del image
    gc.collect()
    if len(payload) > 20 * 1024 * 1024:
        raise RuntimeError(f"{source.name} source exceeds the 20 MiB upload limit")

    uploaded = upload(client, payload, "bench.jpg")
    session = create_session(client, str(uploaded["imageId"]))
    session_id = str(session["sessionId"])
    del payload
    gc.collect()

    timed_render(
        client,
        session_id,
        request_recipe=recipe(exposure_ev=-1.0, denoise=denoise),
        quality=quality,
        max_edge=max_edge,
    )
    durations = [
        timed_render(
            client,
            session_id,
            request_recipe=recipe(
                exposure_ev=0.02 + index * 0.01,
                contrast=8,
                saturation=8,
                denoise=denoise,
            ),
            quality=quality,
            max_edge=max_edge,
        )
        for index in range(iterations)
    ]
    return {
        "source": source.name,
        "n": len(durations),
        "p50": statistics.median(durations),
        "p95": percentile(durations, 0.95),
    }


def export_scenario(
    client: httpx.Client,
    server: ApiServer,
    source: Source,
    iterations: int,
    *,
    measure_memory: bool,
    request_recipe: dict[str, object] | None = None,
) -> dict[str, object]:
    image = make_image(source)
    with tempfile.TemporaryDirectory(prefix="frame-ai-bench-image-") as directory:
        payload = save_jpeg(image, Path(directory) / "source.jpg", 86)
    del image
    gc.collect()

    uploaded = upload(client, payload, "bench-export.jpg")
    session = create_session(client, str(uploaded["imageId"]))
    session_id = str(session["sessionId"])
    revision_id = str(session["activeRevisionId"])
    if request_recipe is not None:
        revision = create_revision(client, session_id, revision_id, request_recipe)
        revision_id = str(revision["activeRevisionId"])
    del payload
    gc.collect()

    def export_once() -> tuple[int, int]:
        response = _expect(
            client.post(
                f"/api/v1/sessions/{session_id}/export",
                json={
                    "revisionId": revision_id,
                    "format": "jpeg",
                    "quality": EXPORT_QUALITY,
                },
            ),
            200,
        )
        return int(response.headers["X-Export-Width"]), int(
            response.headers["X-Export-Height"]
        )

    # Warm up decoding/imports without timing or sampling memory.
    export_once()
    gc.collect()

    durations: list[float] = []
    peak_mb = 0.0
    baseline_mb = 0.0
    dimensions = (0, 0)
    if measure_memory:
        assert server.api_pid is not None
        for index in range(iterations):
            peak, baseline, elapsed, dimensions = sample_peak_rss(
                server.api_pid, export_once
            )
            if index == 0:
                baseline_mb = baseline
            peak_mb = max(peak_mb, peak)
            durations.append(elapsed)
    else:
        for _ in range(iterations):
            started = time.perf_counter()
            dimensions = export_once()
            durations.append((time.perf_counter() - started) * 1000)

    return {
        "source": source.name,
        "recipe": "full" if request_recipe is not None else "neutral",
        "n": len(durations),
        "p50": statistics.median(durations),
        "p95": percentile(durations, 0.95),
        "peak_mb": peak_mb if measure_memory else None,
        "baseline_mb": baseline_mb if measure_memory else None,
        "dimensions": dimensions,
    }


def upload_scenario(client: httpx.Client, iterations: int) -> dict[str, object]:
    source = SOURCES["12mp"]
    image = make_image(source, noisy=True)
    payload = b""
    with tempfile.TemporaryDirectory(prefix="frame-ai-bench-upload-") as directory:
        path = Path(directory) / "noise.jpg"
        low, high = 60, 100
        best = b""
        while low <= high:
            quality = (low + high) // 2
            candidate = save_jpeg(image, path, quality)
            if len(candidate) <= TEMP_UPLOAD_BYTES:
                best = candidate
                low = quality + 1
            else:
                high = quality - 1
        payload = best
    del image
    gc.collect()
    if not payload:
        raise RuntimeError("could not produce a JPEG near 19.5 MiB")

    durations: list[float] = []
    for index in range(iterations):
        started = time.perf_counter()
        _expect(
            client.post(
                "/api/v1/images",
                files={"file": (f"noise-{index}.jpg", payload, "image/jpeg")},
            ),
            201,
        )
        durations.append((time.perf_counter() - started) * 1000)
    return {
        "source": f"{source.name} noisy",
        "n": len(durations),
        "p50": statistics.median(durations),
        "p95": percentile(durations, 0.95),
        "bytes": len(payload),
    }


def format_ms(value: float) -> str:
    return f"{value:.0f} ms"


def pass_fail(value: float, target: float) -> str:
    return "PASS" if value <= target else "**FAIL**"


def build_document(
    *,
    rows: list[tuple[str, str, int, float, float, str, str]],
    memories: list[dict[str, object]],
    memory_limit_mb: float,
    upload: dict[str, object],
    iterations: int,
    memory_runs: int,
    failures: list[str],
    elapsed: float,
) -> str:
    commit = git("rev-parse", "HEAD")
    status = git("status", "--short").replace("\n", ", ") or "clean"
    vm = psutil.virtual_memory()
    lines = [
        "# FRAME AI 阶段 2 性能测量",
        "",
        f"- 日期：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- commit：`{commit}`",
        f"- 工作区：{status}",
        f"- 机器：{platform.platform()}",
        f"- CPU：{platform.processor()}（{psutil.cpu_count(logical=True)} 逻辑核）",
        f"- 内存：{vm.total / 1024**3:.1f} GiB",
        (
            f"- Python：{platform.python_version()}；Pillow {PIL.__version__}；"
            f"NumPy {np.__version__}；psutil {psutil.__version__}"
        ),
        (
            "- 方法：本脚本自启单进程 uvicorn（临时数据目录），预览与导出项先热身一次，"
            f"上传项直接测量；再取 {iterations} 次 p50/p95；"
            f"导出 40 MP 的中性与满配方各使用 {memory_runs} 次 RSS 采样。"
        ),
        "",
        "## §7.8 对照",
        "",
        "| 项目 | 源图 | n | p50 | p95 | 目标 | 结果 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, source, count, p50, p95, target, result in rows:
        lines.append(
            f"| {name} | {source} | {count} | {format_ms(p50)} | {format_ms(p95)} "
            f"| {target} | {result} |"
        )
    lines.append(
        f"| 单次上传 19.5 MiB 解码 | {upload['source']}（{upload['bytes'] / 1024**2:.1f} MiB） "
        f"| {upload['n']} | {format_ms(float(upload['p50']))} "
        f"| {format_ms(float(upload['p95']))} | p95 ≤ 3000 ms "
        f"| {pass_fail(float(upload['p95']), 3000)} |"
    )
    lines += [
        "",
        "## 导出峰值内存",
        "",
    ]
    if not memories:
        lines.append("40 MP 导出的内存测量未完成。")
    else:
        lines += [
            "| 源图 | 配方 | 基线 RSS | 采样峰值 RSS | 上限 | 用时 | 结果 |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for memory in memories:
            lines.append(
                f"| {memory['source']} | {memory['recipe']} "
                f"| {float(memory['baseline_mb']):.0f} MB "
                f"| {float(memory['peak_mb']):.0f} MB | {memory_limit_mb:.0f} MB "
                f"| {format_ms(float(memory['p50']))} "
                f"| {pass_fail(float(memory['peak_mb']), memory_limit_mb)} |"
            )
        lines += [
            "",
            (
                "峰值 RSS 由 10 ms 间隔采样得到，统计 API 进程树（venv 启动器及其子进程）；"
                "上限取 `FRAME_EXPORT_MAX_RSS_MB`。该值包含 API 进程基线，是绝对工作集而不是增量。"
                "中性配方是下限；满配方（含旋转、局部调整、锐化、颗粒）才是实际最坏情况。"
            ),
        ]
    lines += [
        "",
        "## 备注",
        "",
        "- 预览项目均检查 `cacheHit=false`，避免缓存命中污染计时。",
        "- 导出尺寸由响应头 `X-Export-Width/Height` 核对。",
        f"- 全表总耗时 {elapsed:.1f} s。",
        "- 未达标项目保留原始目标值，原因与建议见阶段 2 交接文档。",
    ]
    for failure in failures:
        lines.append(f"- 失败：{failure}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url", help="Use an already running API instead of starting one"
    )
    parser.add_argument(
        "--api-pid", type=int, help="API PID for RSS sampling with --base-url"
    )
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--memory-runs", type=int, default=1)
    parser.add_argument(
        "--output", type=Path, help="Write the Markdown report to this path"
    )
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("--iterations must be positive")

    started = time.perf_counter()
    memory_limit_mb = float(os.environ.get("FRAME_EXPORT_MAX_RSS_MB", "3072"))
    rows: list[tuple[str, str, int, float, float, str, str]] = []
    failures: list[str] = []

    with ApiServer(args.base_url, args.api_pid) as server:
        assert server.client is not None
        client = server.client

        for key in ("1mp", "6mp", "12mp", "24mp"):
            result = render_scenario(
                client,
                SOURCES[key],
                quality="final",
                max_edge=1600,
                denoise=0.0,
                iterations=args.iterations,
            )
            rows.append(
                (
                    "final 预览 1600 px，不含降噪",
                    str(result["source"]),
                    int(result["n"]),
                    float(result["p50"]),
                    float(result["p95"]),
                    "p95 ≤ 500 ms",
                    pass_fail(float(result["p95"]), 500),
                )
            )
            print(
                f"final/no-denoise {result['source']}: p95={result['p95']:.0f} ms",
                flush=True,
            )

        draft = render_scenario(
            client,
            SOURCES["6mp"],
            quality="draft",
            max_edge=960,
            denoise=50.0,
            iterations=args.iterations,
        )
        rows.append(
            (
                "draft 预览 960 px，含降噪",
                str(draft["source"]),
                int(draft["n"]),
                float(draft["p50"]),
                float(draft["p95"]),
                "p95 ≤ 400 ms",
                pass_fail(float(draft["p95"]), 400),
            )
        )
        print(f"draft/denoise {draft['source']}: p95={draft['p95']:.0f} ms", flush=True)

        final_denoise = render_scenario(
            client,
            SOURCES["12mp"],
            quality="final",
            max_edge=1600,
            denoise=50.0,
            iterations=args.iterations,
        )
        rows.append(
            (
                "final 预览 1600 px，含降噪",
                str(final_denoise["source"]),
                int(final_denoise["n"]),
                float(final_denoise["p50"]),
                float(final_denoise["p95"]),
                "p95 ≤ 2500 ms",
                pass_fail(float(final_denoise["p95"]), 2500),
            )
        )
        print(
            f"final/denoise {final_denoise['source']}: p95={final_denoise['p95']:.0f} ms",
            flush=True,
        )

        export_cases: list[
            tuple[str, Source, dict[str, object] | None, str, float | None]
        ] = [
            (
                "12 MP（中性配方）",
                SOURCES["12mp"],
                None,
                "参考（§7.8 仅覆盖 24 MP）",
                None,
            ),
            (
                "24 MP（中性配方，下限）",
                SOURCES["24mp"],
                None,
                "p95 ≤ 20 s",
                20_000,
            ),
            (
                "40 MP（中性配方）",
                SOURCES["40mp"],
                None,
                "参考（§7.8 仅覆盖 24 MP）",
                None,
            ),
            (
                "12 MP（满配方）",
                SOURCES["12mp"],
                full_recipe(),
                "参考（§7.8 仅覆盖 24 MP）",
                None,
            ),
            ("24 MP（满配方）", SOURCES["24mp"], full_recipe(), "p95 ≤ 20 s", 20_000),
            (
                "40 MP（满配方）",
                SOURCES["40mp"],
                full_recipe(),
                "参考（§7.8 仅覆盖 24 MP）",
                None,
            ),
        ]
        for label, source, request_recipe, target, limit_ms in export_cases:
            try:
                export = export_scenario(
                    client,
                    server,
                    source,
                    args.iterations,
                    measure_memory=False,
                    request_recipe=request_recipe,
                )
                p95 = float(export["p95"])
                rows.append(
                    (
                        f"导出 {label}",
                        str(export["source"]),
                        int(export["n"]),
                        float(export["p50"]),
                        p95,
                        target,
                        "—" if limit_ms is None else pass_fail(p95, limit_ms),
                    )
                )
                print(
                    f"export {label}: p95={export['p95']:.0f} ms",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001 - report, keep measuring the rest
                failures.append(f"{label} 导出失败：{type(exc).__name__}: {exc}")

        try:
            upload = upload_scenario(client, args.iterations)
            print(
                f"upload {upload['bytes'] / 1024**2:.1f} MiB: p95={upload['p95']:.0f} ms",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            failures.append(f"19.5 MiB 上传失败：{type(exc).__name__}: {exc}")
            upload = {
                "source": "n/a",
                "n": 0,
                "p50": math.nan,
                "p95": math.nan,
                "bytes": 0,
            }

        memories: list[dict[str, object]] = []
        for label, request_recipe in (("中性配方", None), ("满配方", full_recipe())):
            try:
                memory = export_scenario(
                    client,
                    server,
                    SOURCES["40mp"],
                    args.memory_runs,
                    measure_memory=True,
                    request_recipe=request_recipe,
                )
                memories.append(memory)
                print(
                    f"export 40MP {label} peak RSS={memory['peak_mb']:.0f} MB "
                    f"(baseline {memory['baseline_mb']:.0f} MB), {memory['p50']:.0f} ms",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001
                failures.append(
                    f"40 MP {label}导出/内存测量失败：{type(exc).__name__}: {exc}"
                )

    total_elapsed = time.perf_counter() - started
    document = build_document(
        rows=rows,
        memories=memories,
        memory_limit_mb=memory_limit_mb,
        upload=upload,
        iterations=args.iterations,
        memory_runs=args.memory_runs,
        failures=failures,
        elapsed=total_elapsed,
    )
    print()
    print(document)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(document, encoding="utf-8")
        print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
