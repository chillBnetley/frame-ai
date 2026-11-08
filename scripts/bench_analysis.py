#!/usr/bin/env python3
"""Measure Phase 3 preprocessing, CV feature, and mock end-to-end analysis latency."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "services" / "api"
sys.path.insert(0, str(API_DIR))

from app.analysis.features import extract_features  # noqa: E402
from app.analysis.preprocessing import preprocess_original  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.imaging.loader import load_image  # noqa: E402

ANALYSIS_MAX_EDGE = 1024
MAX_PIXELS = 80_000_000


def build_image(width: int, height: int) -> Image.Image:
    red = np.tile(np.linspace(0, 255, width, dtype=np.uint8), (height, 1))
    green = np.tile(np.linspace(0, 255, height, dtype=np.uint8)[:, None], (1, width))
    blue = np.full((height, width), 128, dtype=np.uint8)
    return Image.fromarray(np.stack([red, green, blue], axis=2), mode="RGB")


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def summarize(samples: list[float]) -> dict[str, float]:
    return {
        "median_ms": round(statistics.median(samples) * 1000.0, 1),
        "p95_ms": round(percentile(samples, 0.95) * 1000.0, 1),
        "min_ms": round(min(samples) * 1000.0, 1),
        "runs": len(samples),
    }


def measure_source(
    name: str,
    width: int,
    height: int,
    directory: Path,
    iterations: int,
) -> dict[str, object]:
    path = directory / f"{name}.jpg"
    build_image(width, height).save(path, format="JPEG", quality=90)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    preprocess_samples: list[float] = []
    feature_samples: list[float] = []
    preprocessed = None
    for run in range(iterations + 1):
        started = time.perf_counter()
        preprocessed = preprocess_original(
            path,
            expected_sha256=digest,
            display_width=width,
            display_height=height,
            exif_orientation=1,
            max_edge=ANALYSIS_MAX_EDGE,
            max_pixels=MAX_PIXELS,
        )
        preprocess_elapsed = time.perf_counter() - started

        started = time.perf_counter()
        loaded = load_image(preprocessed.image.data, max_pixels=MAX_PIXELS)
        extract_features(loaded, display_width=width, display_height=height)
        feature_elapsed = time.perf_counter() - started

        if run > 0:
            preprocess_samples.append(preprocess_elapsed)
            feature_samples.append(feature_elapsed)

    assert preprocessed is not None
    return {
        "source": name,
        "width": width,
        "height": height,
        "megapixels": round(width * height / 1_000_000, 2),
        "analysis_edge": f"{preprocessed.image.width}x{preprocessed.image.height}",
        "preprocess": summarize(preprocess_samples),
        "features": summarize(feature_samples),
        "total": summarize(
            [
                pre + feature
                for pre, feature in zip(preprocess_samples, feature_samples, strict=True)
            ]
        ),
    }


def _api_token(path: Path) -> str | None:
    try:
        token = path.read_text(encoding="ascii").strip()
    except OSError:
        return None
    return token or None


def measure_mock_end_to_end(iterations: int) -> dict[str, object]:
    from fastapi.testclient import TestClient

    from app.main import create_app

    payload = tempfile.TemporaryDirectory(prefix="frame-bench-")
    directory = Path(payload.name)
    image_path = directory / "mock.jpg"
    build_image(1000, 1000).save(image_path, format="JPEG", quality=90)

    settings = Settings(
        data_dir=directory / "data",
        allowed_hosts="testserver",
        allowed_origins="http://testserver",
        mock_scenario="backlit",
        log_level="WARNING",
    )
    samples: list[float] = []
    with TestClient(create_app(settings)) as client:
        token = _api_token(settings.api_token_path)
        if token is not None:
            client.headers["X-FRAME-Token"] = token
        upload = client.post(
            "/api/v1/images",
            files={"file": ("mock.jpg", image_path.read_bytes(), "image/jpeg")},
        )
        upload.raise_for_status()
        image_id = upload.json()["imageId"]
        for run in range(iterations + 1):
            started = time.perf_counter()
            created = client.post(
                "/api/v1/analysis",
                json={"imageId": image_id, "force": True},
            )
            created.raise_for_status()
            analysis_id = created.json()["analysisId"]
            while True:
                status = client.get(f"/api/v1/analysis/{analysis_id}").json()
                if status["status"] in {"completed", "failed"}:
                    break
                time.sleep(0.05)
            elapsed = time.perf_counter() - started
            if status["status"] != "completed":
                raise RuntimeError(f"mock analysis failed: {status}")
            if run > 0:
                samples.append(elapsed)
    payload.cleanup()
    return {
        "source": "1 MP mock task (backlit)",
        "megapixels": 1.0,
        "end_to_end": summarize(samples),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    sources = [
        ("1mp", 1000, 1000),
        ("12mp", 4000, 3000),
        ("40mp", 7296, 5472),
    ]
    with tempfile.TemporaryDirectory(prefix="frame-bench-src-") as temp:
        directory = Path(temp)
        results: dict[str, object] = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "iterations": args.iterations,
            "pipeline": [
                measure_source(name, width, height, directory, args.iterations)
                for name, width, height in sources
            ],
            "mock_task": measure_mock_end_to_end(args.iterations),
        }

    rendered = json.dumps(results, indent=2, ensure_ascii=False)
    print(rendered)
    if args.json is not None:
        args.json.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
