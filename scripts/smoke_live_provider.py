#!/usr/bin/env python3
"""Opt-in smoke test for the configured live analysis providers.

The script runs the same stages as a real task (vision -> CV features ->
candidate diagnosis -> decision model) without touching the database, and only
prints schema/shape/latency information. It never prints prompts, image bytes,
Base64, API keys, or raw provider responses.

It runs only when both providers are configured as ``openai`` with a key, model,
and base URL. Otherwise it prints ``SKIPPED`` and exits 0; pass
``--require-live`` to turn an unconfigured run into an error (exit 2).

Usage (from any directory):
    services/api/.venv/Scripts/python.exe scripts/smoke_live_provider.py
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "services" / "api"
sys.path.insert(0, str(API_DIR))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from app.ai.base import DecisionRequest, ModelImage, VisionRequest  # noqa: E402
from app.ai.contracts import AnalysisOptions  # noqa: E402
from app.ai.errors import ProviderError  # noqa: E402
from app.ai.factory import build_provider_bundle  # noqa: E402
from app.analysis.decision_validation import validate_decision  # noqa: E402
from app.analysis.diagnosis import (  # noqa: E402
    DiagnosisContext,
    build_candidates,
    sample_regions,
)
from app.analysis.features import extract_features  # noqa: E402
from app.analysis.regions import build_regions  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.imaging.loader import load_image  # noqa: E402


def _missing_live_settings(settings: Settings) -> list[str]:
    missing: list[str] = []
    if settings.vision_provider != "openai":
        missing.append("FRAME_VISION_PROVIDER=openai")
    if settings.decision_provider != "openai":
        missing.append("FRAME_DECISION_PROVIDER=openai")
    if not settings.vision_api_key.get_secret_value():
        missing.append("FRAME_VISION_API_KEY")
    if not settings.vision_model:
        missing.append("FRAME_VISION_MODEL")
    if not settings.vision_api_base_url:
        missing.append("FRAME_VISION_API_BASE_URL")
    if not settings.decision_api_key.get_secret_value():
        missing.append("FRAME_DECISION_API_KEY")
    if not settings.decision_model:
        missing.append("FRAME_DECISION_MODEL")
    if not settings.decision_api_base_url:
        missing.append("FRAME_DECISION_API_BASE_URL")
    return missing


def _synthetic_jpeg() -> bytes:
    size = 256
    gradient = np.linspace(0, 255, size, dtype=np.uint8)
    red = np.tile(gradient, (size, 1))
    green = np.tile(gradient[:, None], (1, size))
    blue = np.full((size, size), 140, dtype=np.uint8)
    image = Image.fromarray(np.stack([red, green, blue], axis=2), mode="RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=88)
    return buffer.getvalue()


def _load_smoke_image(path: Path | None) -> tuple[bytes, str]:
    if path is None:
        return _synthetic_jpeg(), "image/jpeg"
    suffix = path.suffix.lower()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(suffix)
    if mime is None:
        raise ValueError(f"unsupported smoke image extension: {suffix or '(none)'}")
    return path.read_bytes(), mime


def run_smoke(image_path: Path | None) -> dict[str, Any]:
    settings = Settings()
    missing = _missing_live_settings(settings)
    if missing:
        return {"status": "skipped", "missing": missing}

    bundle = build_provider_bundle(settings)
    if bundle.is_mock:
        raise RuntimeError("provider bundle resolved to mock; refusing to report a live smoke")

    data, mime_type = _load_smoke_image(image_path)
    started = time.perf_counter()
    loaded = load_image(data, max_pixels=settings.max_image_pixels)
    load_seconds = time.perf_counter() - started

    model_image = ModelImage(
        data=data,
        mime_type=mime_type,
        width=loaded.width,
        height=loaded.height,
    )
    options = AnalysisOptions()

    started = time.perf_counter()
    vision = bundle.vision.analyze(
        VisionRequest(
            image=model_image,
            options=options,
            measurements=extract_features(
                loaded,
                display_width=loaded.width,
                display_height=loaded.height,
            ),
        )
    )
    vision_seconds = time.perf_counter() - started

    started = time.perf_counter()
    measurements = extract_features(
        loaded,
        display_width=loaded.width,
        display_height=loaded.height,
    )
    assignment = build_regions(vision.subjects, subject_detection=True)
    region_samples = sample_regions(loaded, assignment)
    candidates = build_candidates(
        DiagnosisContext(
            vision=vision,
            measurements=measurements,
            options=options,
            assignment=assignment,
            region_samples=region_samples,
        )
    )
    decision = bundle.decision.diagnose(
        DecisionRequest(
            vision=vision,
            measurements=measurements,
            candidates=candidates.candidates,
            options=options,
        )
    )
    validated = validate_decision(
        decision,
        candidates.candidates,
        tuple(region.id for region in assignment.regions),
    )
    decision_seconds = time.perf_counter() - started

    return {
        "status": "ok",
        "visionProvider": bundle.vision.name,
        "visionModel": bundle.vision.model,
        "decisionProvider": bundle.decision.name,
        "decisionModel": bundle.decision.model,
        "image": {"width": loaded.width, "height": loaded.height, "bytes": len(data)},
        "latencySeconds": {
            "load": round(load_seconds, 3),
            "vision": round(vision_seconds, 3),
            "featuresAndDecision": round(decision_seconds, 3),
        },
        "result": {
            "scene": vision.scene.primary.value,
            "subjects": len(vision.subjects),
            "candidateIssues": len(candidates.candidates),
            "issues": len(validated.selections),
            "recommendations": len(validated.recommendations),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Opt-in live smoke test for analysis providers.")
    parser.add_argument("--image", type=Path, help="Optional local image to send")
    parser.add_argument(
        "--require-live",
        action="store_true",
        help="Exit 2 instead of skipping when live providers are not configured",
    )
    args = parser.parse_args(argv)

    try:
        result = run_smoke(args.image)
    except (ProviderError, RuntimeError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {"status": "error", "message": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1

    if result["status"] == "skipped":
        print("SKIPPED: live providers are not configured.")
        for name in result["missing"]:
            print(f"  missing: {name}")
        print("Set the listed FRAME_* variables, then rerun this script.")
        return 2 if args.require_live else 0

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
