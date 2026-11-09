#!/usr/bin/env python3
"""Stage 6 performance baseline: fit, prompt, plan, render, save, and token size.

The benchmark starts an in-process app with a temporary data directory and the
mock provider. It measures local engine/API cost only; real provider latency is
recorded separately in the provider usage ledger and is not projected here.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import statistics
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "services" / "api"
sys.path.insert(0, str(API_DIR))

from app.ai.base import PlannerRequest
from app.ai.prompts import build_planner_messages
from app.core.config import Settings
from app.main import create_app
from app.models.analysis_report import AnalysisReport
from app.models.conversion import ConversionMode
from app.models.photographer import PhotographerPreferences, PlannerMode
from app.models.recipe import EditRecipe
from app.models.style_profile import StyleProfile
from app.photographer.style_generation import build_style_context

logging.getLogger().setLevel(logging.WARNING)

STYLE_IDS = ("fan_ho", "ansel_adams", "environmental_portrait")
MODES = (ConversionMode.NATURAL, ConversionMode.STYLE, ConversionMode.CREATIVE)
PREFERENCES = PhotographerPreferences(naturalness=0.5, adjustment_strength=1.0)
SIZE = (1200, 800)


def make_image(path: Path) -> bytes:
    width, height = SIZE
    y, x = np.mgrid[0:height, 0:width]
    image = np.zeros((height, width, 3), dtype=np.float32)
    image[..., 0] = 0.18 + 0.45 * (x / width)
    image[..., 1] = 0.16 + 0.35 * (y / height)
    image[..., 2] = 0.2 + 0.25 * (x / width)
    image[30 : height - 30, 180:220] = (0.08, 0.07, 0.06)
    image[40:90, 900:980] = (0.95, 0.9, 0.8)
    pixels = np.clip(image * 255.0 + 0.5, 0, 255).astype(np.uint8)
    Image.fromarray(pixels, mode="RGB").save(path, format="JPEG", quality=90)
    return path.read_bytes()


def summarize(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    p95 = ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]
    return {
        "median_ms": round(statistics.median(samples) * 1000.0, 1),
        "p95_ms": round(p95 * 1000.0, 1),
        "runs": len(samples),
    }


def usage_rows(database: Path) -> list[dict[str, object]]:
    import sqlite3

    if not database.is_file():
        return []
    connection = sqlite3.connect(database)
    try:
        cursor = connection.execute(
            "SELECT provider, requests, tokens_estimated, tokens_reported "
            "FROM provider_usage ORDER BY provider"
        )
        return [
            {
                "provider": row[0],
                "requests": row[1],
                "tokens_estimated": row[2],
                "tokens_reported": row[3],
            }
            for row in cursor.fetchall()
        ]
    except sqlite3.Error:
        return []
    finally:
        connection.close()


def run(iterations: int) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="frame-stage6-bench-") as tmp:
        data_dir = Path(tmp) / "data"
        settings = Settings(
            _env_file=None,
            data_dir=data_dir,
            allowed_origins="http://testserver",
            allowed_hosts="testserver",
            api_auth_enabled=False,
            vision_provider="mock",
            decision_provider="mock",
            mock_scenario="portrait",
            analysis_max_concurrency=1,
            analysis_max_attempts=1,
            log_level="WARNING",
        )
        source = Path(tmp) / "bench.jpg"
        payload = make_image(source)
        report: AnalysisReport
        session_id: str
        analysis_ms: float
        render_samples: dict[str, list[float]] = {}
        plan_samples: list[float] = []
        save_samples: list[float] = []

        with TestClient(create_app(settings)) as client:
            started = time.perf_counter()
            uploaded = client.post(
                "/api/v1/images",
                files={"file": ("bench.jpg", payload, "image/jpeg")},
            )
            uploaded.raise_for_status()
            image_id = uploaded.json()["imageId"]
            session = client.post("/api/v1/sessions", json={"imageId": image_id})
            session.raise_for_status()
            session_id = session.json()["sessionId"]
            created = client.post("/api/v1/analysis", json={"imageId": image_id})
            created.raise_for_status()
            analysis_id = created.json()["analysisId"]
            deadline = time.monotonic() + 30
            while True:
                status = client.get(f"/api/v1/analysis/{analysis_id}").json()
                if status["status"] in {"completed", "failed"}:
                    assert status["status"] == "completed", status
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError("analysis benchmark timed out")
                time.sleep(0.02)
            analysis_ms = (time.perf_counter() - started) * 1000.0
            report = AnalysisReport.model_validate(
                client.get(f"/api/v1/analysis/{analysis_id}/result").json()
            )
            current_recipe = EditRecipe.model_validate(
                client.get(f"/api/v1/sessions/{session_id}").json()["revision"][
                    "recipe"
                ]
            )

            profiles: dict[str, StyleProfile] = {}
            for style_id in STYLE_IDS:
                detail = client.get(f"/api/v1/styles/{style_id}")
                detail.raise_for_status()
                profiles[style_id] = StyleProfile.model_validate(detail.json()["style"])

            fit_samples: list[float] = []
            prompt_sizes: list[int] = []
            for _ in range(iterations):
                for style_id in STYLE_IDS:
                    started = time.perf_counter()
                    fit = client.get(
                        f"/api/v1/styles/{style_id}/fit",
                        params={"image_id": image_id, "alternatives": 3},
                    )
                    fit.raise_for_status()
                    fit_samples.append(time.perf_counter() - started)

                    profile = profiles[style_id]
                    context = build_style_context(
                        profile,
                        report,
                        mode=ConversionMode.STYLE,
                        strength=0.7,
                        image_id=image_id,
                        image_sha256=report.image.sha256,
                    )
                    messages = build_planner_messages(
                        PlannerRequest(
                            analysis=report,
                            recipe=current_recipe,
                            preferences=PREFERENCES,
                            mode=PlannerMode.STYLE,
                            style=profile.to_style_definition(),
                            style_strength=0.7,
                            style_context=context,
                        )
                    )
                    prompt_sizes.append(
                        sum(
                            len(str(item["content"]).encode("utf-8"))
                            for item in messages
                        )
                    )

            for mode in MODES:
                for style_id in STYLE_IDS:
                    started = time.perf_counter()
                    plan = client.post(
                        "/api/v1/ai/photographer/plan",
                        json={
                            "sessionId": session_id,
                            "analysisId": analysis_id,
                            "mode": "style",
                            "styleId": style_id,
                            "styleStrength": 0.7,
                            "conversionMode": mode.value,
                        },
                    )
                    plan.raise_for_status()
                    plan_samples.append(time.perf_counter() - started)
                    body = plan.json()
                    started = time.perf_counter()
                    rendered = client.post(
                        f"/api/v1/sessions/{session_id}/render",
                        json={"recipe": body["recipe"], "quality": "final"},
                    )
                    rendered.raise_for_status()
                    render_samples.setdefault(mode.value, []).append(
                        time.perf_counter() - started
                    )
                    if not save_samples:
                        started = time.perf_counter()
                        accepted = client.post(
                            f"/api/v1/ai/photographer/plan/{body['planId']}/accept",
                            json={
                                "parentRevisionId": body["baseRevisionId"],
                                "renderKey": "a" * 64,
                            },
                        )
                        accepted.raise_for_status()
                        save_samples.append(time.perf_counter() - started)

            usage = usage_rows(settings.database_path)

        return {
            "environment": {
                "width": SIZE[0],
                "height": SIZE[1],
                "iterations": iterations,
                "provider": "mock",
                "python": sys.version.split()[0],
            },
            "analysis_ms": round(analysis_ms, 1),
            "fit": summarize(fit_samples),
            "plan": summarize(plan_samples),
            "render": {
                mode: summarize(values) for mode, values in render_samples.items()
            },
            "save": summarize(save_samples),
            "prompt": {
                "median_bytes": int(statistics.median(prompt_sizes)),
                "estimated_tokens": math.ceil(statistics.median(prompt_sizes) / 4),
                "samples": len(prompt_sizes),
            },
            "usage_ledger": usage,
            "note": "Mock provider and local disk; real provider latency/tokens are separate.",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--iterations", type=int, default=10, help="Fit/prompt repetitions."
    )
    parser.add_argument(
        "--json", action="store_true", help="Print machine-readable JSON."
    )
    args = parser.parse_args()
    result = run(max(1, args.iterations))
    print(
        json.dumps(result, indent=2, ensure_ascii=False)
        if args.json
        else format_markdown(result)
    )
    return 0


def format_markdown(result: dict[str, object]) -> str:
    env = result["environment"]
    fit = result["fit"]
    plan = result["plan"]
    save = result["save"]
    prompt = result["prompt"]
    lines = [
        "## Stage 6 benchmark",
        "",
        f"- Image: {env['width']}x{env['height']} ({env['provider']}), Python {env['python']}",
        f"- Analysis (upload + mock analyze): {result['analysis_ms']} ms",
        f"- Fit API: median {fit['median_ms']} ms, p95 {fit['p95_ms']} ms ({fit['runs']} runs)",
        f"- Plan API (mock): median {plan['median_ms']} ms, p95 {plan['p95_ms']} ms",
        f"- Save/accept: median {save['median_ms']} ms, p95 {save['p95_ms']} ms",
        f"- Planner prompt: {prompt['median_bytes']} bytes ~ {prompt['estimated_tokens']} tokens",
        "",
        "| Render mode | median ms | p95 ms | runs |",
        "| --- | --- | --- | --- |",
    ]
    for mode, timing in result["render"].items():
        lines.append(
            f"| {mode} | {timing['median_ms']} | {timing['p95_ms']} | {timing['runs']} |"
        )
    lines.extend(
        [
            "",
            "### Usage ledger",
            "",
            "| provider | requests | reported tokens | estimated tokens |",
            "| --- | --- | --- | --- |",
        ]
    )
    for row in result["usage_ledger"]:
        lines.append(
            f"| {row['provider']} | {row['requests']} | {row['tokens_reported']} | "
            f"{row['tokens_estimated']} |"
        )
    if not result["usage_ledger"]:
        lines.append("| (mock provider records no HTTP attempts) | 0 | 0 | 0 |")
    lines.extend(["", f"_{result['note']}_"])
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
