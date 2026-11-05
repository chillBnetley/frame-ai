#!/usr/bin/env python3
"""Measure the Task 8 proxy and mask-weight caches by calling them directly.

Nothing here goes through HTTP: every number describes the cached function and
its uncached alternative on the same machine, so the report cannot be mistaken
for an end-to-end latency claim.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import platform
import statistics
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import psutil
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "services" / "api"
sys.path.insert(0, str(API_DIR))

from app.imaging.loader import load_proxy, proxy_cache_directory  # noqa: E402
from app.imaging.local_masks import (  # noqa: E402
    MASK_CACHE_ENTRY_LIMIT_BYTES,
    clear_mask_cache,
    configure_mask_cache,
    mask_cache_stats,
    mask_weights,
)
from app.models.recipe import UserMask  # noqa: E402
from app.services.proxy_cache import DecodedProxyCache  # noqa: E402

MB = 1024 * 1024
PROXY_CACHE_MB = 64
MASK_CACHE_MB = 64
RENDER_EDGE = 1600

SOURCES = {
    "6 MP": (3000, 2000),
    "24 MP": (6000, 4000),
}

MASKS = (
    UserMask(
        id="mask_bench_ellipse",
        shape="ellipse",
        x=0.18,
        y=0.2,
        width=0.46,
        height=0.5,
        feather=25.0,
        opacity=100.0,
        inverted=False,
    ),
    UserMask(
        id="mask_bench_shadow",
        shape="rectangle",
        x=0.05,
        y=0.6,
        width=0.4,
        height=0.35,
        feather=40.0,
        opacity=70.0,
        inverted=False,
    ),
    UserMask(
        id="mask_bench_sky",
        shape="rectangle",
        x=0.0,
        y=0.0,
        width=1.0,
        height=0.3,
        feather=15.0,
        opacity=100.0,
        inverted=True,
    ),
)


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def rss_mb() -> float:
    return psutil.Process(os.getpid()).memory_info().rss / MB


def timed(operation: Callable[[], Any]) -> tuple[float, float, Any]:
    """Run one operation and return (elapsed ms, peak RSS MB during it, result)."""
    gc.collect()
    peak = rss_mb()
    stop = threading.Event()

    def sample() -> None:
        nonlocal peak
        while not stop.wait(0.005):
            peak = max(peak, rss_mb())

    thread = threading.Thread(target=sample, daemon=True)
    thread.start()
    started = time.perf_counter()
    try:
        result = operation()
    finally:
        elapsed = (time.perf_counter() - started) * 1000
        stop.set()
        thread.join(timeout=2)
    return elapsed, peak, result


def summarize(samples: list[float], peaks: list[float]) -> dict[str, float]:
    return {
        "runs": len(samples),
        "median_ms": round(statistics.median(samples), 2),
        "p95_ms": round(percentile(samples, 0.95), 2),
        "peak_rss_mb": round(max(peaks), 1),
    }


def build_source(width: int, height: int) -> bytes:
    x = np.linspace(0.0, 1.0, width, dtype=np.float32)
    y = np.linspace(0.0, 1.0, height, dtype=np.float32)
    pixels = np.empty((height, width, 3), dtype=np.uint8)
    pixels[:, :, 0] = np.clip(30.0 + 190.0 * x, 0, 255)[None, :]
    pixels[:, :, 1] = np.clip(40.0 + 160.0 * y, 0, 255)[:, None]
    pixels[:, :, 2] = np.clip(70.0 + 120.0 * (1.0 - x[None, :] * y[:, None]), 0, 255)
    image = Image.fromarray(pixels, mode="RGB")
    with tempfile.TemporaryDirectory(prefix="frame-bench-source-") as directory:
        path = Path(directory) / "source.jpg"
        image.save(path, format="JPEG", quality=86, subsampling=0)
        payload = path.read_bytes()
    del image, pixels
    return payload


def proxy_case(
    directory: Path, label: str, size: tuple[int, int], iterations: int
) -> dict[str, Any]:
    width, height = size
    payload = build_source(width, height)
    cache_dir = proxy_cache_directory(directory / label.replace(" ", "_"))
    cache = DecodedProxyCache(PROXY_CACHE_MB * MB)

    def decode(digest: str) -> Any:
        return load_proxy(
            payload,
            original_sha256=digest,
            max_edge=RENDER_EDGE,
            cache_dir=cache_dir,
            max_pixels=None,
        )

    cold: list[float] = []
    disk: list[float] = []
    hit: list[float] = []
    cold_peaks: list[float] = []
    disk_peaks: list[float] = []
    hit_peaks: list[float] = []
    max_diff = 0.0
    proxy_bytes = 0

    for index in range(iterations):
        # A distinct digest per run means the on-disk proxy is always absent,
        # so the first call below is a real cold decode of the original.
        digest = hashlib.sha256(payload + f"|{index}".encode()).hexdigest()

        cold_ms, cold_peak, first = timed(lambda current=digest: decode(current))
        disk_ms, disk_peak, second = timed(lambda current=digest: decode(current))
        key = cache.key_for(digest, RENDER_EDGE)
        cache.put(key, first)
        hit_ms, hit_peak, third = timed(lambda stored=key: cache.get(stored))

        if hit_ms is None or third is None:
            raise RuntimeError(f"{label}: the proxy cache refused an 8-bit proxy")
        max_diff = max(
            max_diff,
            float(np.abs(first.rgb - second.rgb).max()),
            float(np.abs(first.rgb - third.rgb).max()),
        )
        proxy_bytes = int(third.rgb.nbytes)
        cold.append(cold_ms)
        disk.append(disk_ms)
        hit.append(hit_ms)
        cold_peaks.append(cold_peak)
        disk_peaks.append(disk_peak)
        hit_peaks.append(hit_peak)

    stats = cache.stats()
    del first, second, third
    gc.collect()
    return {
        "case": f"代理 {label} → {RENDER_EDGE} px",
        "cold": summarize(cold, cold_peaks),
        "disk": summarize(disk, disk_peaks),
        "memory": summarize(hit, hit_peaks),
        # The cache stores the 8-bit form; the render pipeline works on float32.
        "entry_bytes_mb": round(stats.bytes_used / max(1, stats.entries) / MB, 2),
        "decoded_float32_mb": round(proxy_bytes / MB, 2),
        "cache_bytes_used_mb": round(stats.bytes_used / MB, 2),
        "cache_entries": stats.entries,
        "max_pixel_diff": max_diff,
    }


def mask_case(
    label: str,
    masks: tuple[UserMask, ...],
    *,
    canvas: tuple[int, int],
    iterations: int,
) -> dict[str, Any]:
    output_width, output_height = canvas

    def compute(mask: UserMask) -> Any:
        return mask_weights(
            mask,
            output_width=output_width,
            output_height=output_height,
            source_width=output_width,
            source_height=output_height,
            rotation_deg=0.0,
            crop=None,
        )

    configure_mask_cache(0)
    clear_mask_cache()
    direct: list[float] = []
    direct_peaks: list[float] = []
    references = []
    for mask in masks:
        elapsed, peak, weights = timed(lambda current=mask: compute(current))
        references.append(weights.copy())
        direct.append(elapsed)
        direct_peaks.append(peak)
    # One extra pass per mask so the direct numbers are not dominated by the
    # first-touch page faults of freshly allocated canvases.
    for mask in masks:
        elapsed, peak, _ = timed(lambda current=mask: compute(current))
        direct.append(elapsed)
        direct_peaks.append(peak)

    configure_mask_cache(MASK_CACHE_MB * MB)
    clear_mask_cache()
    miss: list[float] = []
    miss_peaks: list[float] = []
    cached: list[float] = []
    cached_peaks: list[float] = []
    entries_after: list[int] = []
    max_diff = 0.0
    for index, mask in enumerate(masks):
        elapsed, peak, _ = timed(lambda current=mask: compute(current))
        miss.append(elapsed)
        miss_peaks.append(peak)
        entries_after.append(mask_cache_stats().entries)
        reference = references[index]
        for _ in range(iterations):
            hit_elapsed, hit_peak, hit_weights = timed(
                lambda current=mask: compute(current)
            )
            cached.append(hit_elapsed)
            cached_peaks.append(hit_peak)
            max_diff = max(max_diff, float(np.abs(hit_weights - reference).max()))

    stats = mask_cache_stats()
    entry_bytes = output_width * output_height * 4
    result = {
        "case": f"蒙版权重 {label}（{output_width}×{output_height}）",
        "masks": len(masks),
        "direct": summarize(direct, direct_peaks),
        "first_call": summarize(miss, miss_peaks),
        "cached": summarize(cached, cached_peaks),
        "entry_bytes_mb": round(entry_bytes / MB, 2),
        "entry_within_cap": entry_bytes <= MASK_CACHE_ENTRY_LIMIT_BYTES,
        "entries_after_each": entries_after,
        "hits": stats.hits,
        "misses": stats.misses,
        "entries": stats.entries,
        "bytes_used_mb": round(stats.bytes_used / MB, 2),
        "max_pixel_diff": max_diff,
    }
    clear_mask_cache()
    configure_mask_cache(0)
    del references
    gc.collect()
    return result


def _row(case: dict[str, Any], uncached: str, cached: str) -> str:
    before = case[uncached]
    after = case[cached]
    return (
        f"| {case['case']} "
        f"| {float(before['median_ms']):.2f} ms "
        f"| {float(before['p95_ms']):.2f} ms "
        f"| {float(after['median_ms']):.2f} ms "
        f"| {float(after['p95_ms']):.2f} ms "
        f"| {float(case['entry_bytes_mb']):.2f} MB "
        f"| {float(after['peak_rss_mb']):.0f} MB |"
    )


def _ms(case: dict[str, Any], key: str, field: str) -> float:
    return float(case[key][field])


def build_document(
    *,
    proxy: list[dict[str, Any]],
    masks: list[dict[str, Any]],
    iterations: int,
    elapsed: float,
) -> str:
    header = [
        "# FRAME AI 阶段 4 Task 8 缓存测量",
        "",
        f"- 日期：{time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime())}",
        f"- 机器：{platform.platform()}；CPU：{platform.processor()}",
        f"- 内存：{psutil.virtual_memory().total / 1024**3:.1f} GiB",
        (
            f"- Python：{platform.python_version()}；Pillow {Image.__version__}；"
            f"NumPy {np.__version__}；psutil {psutil.__version__}"
        ),
        (
            f"- 方法：直接调用缓存函数本体，不经过 HTTP。每项重复 {iterations} 次，"
            "取中位数与 p95；RSS 为本进程 5 ms 间隔采样的峰值。"
            "代理缓存预算 64 MB、蒙版权重缓存预算 64 MB（单条上限 24 MB）为产品默认值。"
        ),
        "- 这些数字只描述被缓存函数本身的开销，不能当作端到端预览或导出耗时。",
        "",
        "## 代理缓存",
        "",
        "| 场景 | 冷解码 p50 | 冷解码 p95 | 内存命中 p50 | 内存命中 p95 | 缓存单条（uint8） | 峰值 RSS |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    rows = [_row(case, "cold", "memory") for case in proxy]
    disk_rows = [
        (
            f"- {case['case']}：磁盘代理命中 p50 {_ms(case, 'disk', 'median_ms'):.2f} ms、"
            f"p95 {_ms(case, 'disk', 'p95_ms'):.2f} ms；"
            f"缓存占用 {float(case['cache_bytes_used_mb']):.2f} MB "
            f"（{case['cache_entries']} 条）；"
            f"三条路径最大像素差 {float(case['max_pixel_diff']):.6f}。"
        )
        for case in proxy
    ]
    mask_header = [
        "",
        "## 蒙版权重缓存",
        "",
        "| 场景 | 未缓存 p50 | 未缓存 p95 | 命中 p50 | 命中 p95 | 单条（float32） | 峰值 RSS |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    mask_rows = [_row(case, "direct", "cached") for case in masks]
    mask_notes = [
        (
            f"- {case['case']}：{case['masks']} 个蒙版；首次调用 p50 "
            f"{_ms(case, 'first_call', 'median_ms'):.2f} ms；"
            f"缓存条目 {case['entries']}，命中 {case['hits']}，未命中 {case['misses']}，"
            f"占用 {float(case['bytes_used_mb']):.2f} MB；"
            f"单条是否进入缓存：{'是' if case['entry_within_cap'] else '否（超过 24 MB 单条上限，按未缓存速度执行）'}；"
            f"命中像素与直接计算最大差 {float(case['max_pixel_diff']):.6f}。"
        )
        for case in masks
    ]
    footer = [
        "",
        "## 原始数据",
        "",
        "```json",
        json.dumps({"proxy": proxy, "masks": masks}, ensure_ascii=False, indent=2),
        "```",
        "",
        f"- 总耗时 {elapsed:.1f} s。",
        "",
    ]
    return "\n".join(
        [*header, *rows, *disk_rows, *mask_header, *mask_rows, *mask_notes, *footer]
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--output", type=Path, help="Write the Markdown report here")
    parser.add_argument(
        "--json-output", type=Path, help="Write raw measurements as JSON"
    )
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("--iterations must be positive")

    started = time.perf_counter()
    proxy_results: list[dict[str, Any]] = []
    mask_results: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="frame-bench-cache-") as directory:
        root = Path(directory)
        for label, size in SOURCES.items():
            case = proxy_case(root, label, size, args.iterations)
            proxy_results.append(case)
            print(
                f"proxy {label}: cold p50={case['cold']['median_ms']:.1f} ms, "
                f"disk p50={case['disk']['median_ms']:.1f} ms, "
                f"memory p50={case['memory']['median_ms']:.2f} ms",
                flush=True,
            )

    canvas_preview = (RENDER_EDGE, 1067)
    canvas_full = (6000, 4000)
    mask_scenarios = [
        ("1 蒙版 / 预览画布", (MASKS[0],), canvas_preview),
        ("3 蒙版 / 预览画布", MASKS, canvas_preview),
        ("3 蒙版 / 24 MP 画布", MASKS, canvas_full),
    ]
    for label, masks, canvas in mask_scenarios:
        case = mask_case(label, masks, canvas=canvas, iterations=args.iterations)
        mask_results.append(case)
        print(
            f"masks {label}: direct p50={case['direct']['median_ms']:.1f} ms, "
            f"cached p50={case['cached']['median_ms']:.2f} ms, "
            f"entries={case['entries']}/{case['masks']}",
            flush=True,
        )

    elapsed = time.perf_counter() - started
    document = build_document(
        proxy=proxy_results,
        masks=mask_results,
        iterations=args.iterations,
        elapsed=elapsed,
    )
    print()
    print(document)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(document, encoding="utf-8")
        print(f"wrote {args.output}")
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(
                {"proxy": proxy_results, "masks": mask_results},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"wrote {args.json_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
