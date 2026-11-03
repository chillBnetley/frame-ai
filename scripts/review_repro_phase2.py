#!/usr/bin/env python3
"""Reproduce the Phase 2 review findings outside pytest.

Usage (from the repository root):
    services/api/.venv/Scripts/python.exe scripts/review_repro_phase2.py rotation
    services/api/.venv/Scripts/python.exe scripts/review_repro_phase2.py icc
    services/api/.venv/Scripts/python.exe scripts/review_repro_phase2.py \
        export --mp 24 --recipe full

Rotation and ICC checks exit 1 while the R2-01 / R2-02 defects are present and
0 once fixed. The export command measures the real export path and succeeds
whenever the measurement completes; it is the benchmark referenced by R2-03.
"""

from __future__ import annotations

import argparse
import gc
import math
import sys
import tempfile
import threading
import time
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageCms

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "services" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from app.imaging.geometry import rotate_inscribed
from app.imaging.loader import load_image
from app.imaging.output import encode_image
from app.imaging.pipeline import render
from app.models.recipe import Adjustments
from tests.icc_support import build_display_p3_like_profile

ROTATION_SIZES = [
    (1600, 1067),
    (1067, 1600),
    (1200, 1200),
    (1600, 900),
    (2000, 500),
    (160, 100),
]
ROTATION_ANGLES = [0.25, 3.0, 7.5, 15.0, -15.0]

P3_SAMPLE_COLORS = [(200, 60, 60), (60, 200, 60), (230, 160, 120)]


def _fail(message: str) -> None:
    print(f"FAIL: {message}")


def check_rotation() -> int:
    """R2-01: the inscribed canvas must never sample outside the source."""
    original_border = cv2.BORDER_REFLECT_101
    worst_fraction = 0.0
    failures: list[str] = []
    try:
        # Make out-of-source sampling visible as black instead of mirrored.
        cv2.BORDER_REFLECT_101 = cv2.BORDER_CONSTANT
        for width, height in ROTATION_SIZES:
            for angle in ROTATION_ANGLES:
                for quality in ("draft", "final"):
                    rgb = np.ones((height, width, 3), dtype=np.float32)
                    rotated = rotate_inscribed(rgb, angle, quality=quality)
                    fraction = float((rotated.min(axis=2) < 0.5).mean())
                    worst_fraction = max(worst_fraction, fraction)
                    if fraction > 0.0:
                        failures.append(
                            f"{width}x{height} {angle:+.2f} deg {quality}: "
                            f"{fraction * 100:.3f}% outside"
                        )
    finally:
        cv2.BORDER_REFLECT_101 = original_border

    height, width = 600, 900
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    encoded = np.stack([xx / width, yy / height, np.zeros_like(xx)], axis=-1)
    rotated_encoded = rotate_inscribed(encoded, 10.0, quality="final")
    middle_row = rotated_encoded[rotated_encoded.shape[0] // 2, :, :2]
    content_span = float(np.hypot(*(middle_row[-1] - middle_row[0])))

    print(f"worst out-of-source fraction: {worst_fraction * 100:.3f}%")
    print(f"content span across the middle row: {content_span:.4f} (must be <= 1)")
    for failure in failures[:8]:
        _fail(failure)
    if len(failures) > 8:
        print(f"... {len(failures) - 8} more combinations")
    if content_span > 1.0 + 1e-6:
        _fail(f"rotation content is scaled up to {content_span:.4f}")
    return 0 if not failures and content_span <= 1.0 + 1e-6 else 1


def check_icc() -> int:
    """R2-02: embedded RGB ICC profiles must be converted to sRGB on load."""
    profile_bytes = build_display_p3_like_profile()
    try:
        source_profile = ImageCms.ImageCmsProfile(BytesIO(profile_bytes))
    except (ImageCms.PyCMSError, OSError) as exc:
        _fail(f"could not build a valid test ICC profile: {exc}")
        return 2

    destination_profile = ImageCms.createProfile("sRGB")
    sample = Image.new("RGB", (24, 8))
    for index, color in enumerate(P3_SAMPLE_COLORS):
        sample.paste(color, (index * 8, 0, index * 8 + 8, 8))

    with tempfile.TemporaryDirectory(prefix="frame-ai-repro-icc-") as directory:
        path = Path(directory) / "p3.jpg"
        sample.save(
            path, format="JPEG", quality=100, subsampling=0, icc_profile=profile_bytes
        )
        with Image.open(path) as opened:
            decoded = opened.convert("RGB")
        expected_image = ImageCms.profileToProfile(
            decoded,
            source_profile,
            destination_profile,
            renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
            outputMode="RGB",
            flags=ImageCms.Flags.BLACKPOINTCOMPENSATION,
        )
        if expected_image is None:
            _fail("lcms refused the reference conversion")
            return 2
        expected = np.asarray(expected_image, dtype=np.float64)
        actual = load_image(path).rgb.astype(np.float64) * 255.0

    # Sample block centres so JPEG block boundaries cannot skew the numbers.
    samples = [(4, 4), (12, 4), (20, 4)]
    worst = 0.0
    for x, y in samples:
        difference = np.abs(actual[y, x] - expected[y, x])
        worst = max(worst, float(difference.max()))
        print(
            f"input {tuple(int(v) for v in np.asarray(decoded)[y, x])} -> "
            f"loader {tuple(round(v) for v in actual[y, x])} "
            f"expected {tuple(int(v) for v in expected[y, x])} "
            f"max channel diff {difference.max():.0f}"
        )
    if worst > 3.0:
        _fail(
            f"embedded P3-like profile was not converted (worst channel diff {worst:.0f})"
        )
        return 1
    print("embedded ICC profile matches the lcms sRGB reference")
    return 0


def _make_source(width: int, height: int) -> Image.Image:
    x = np.linspace(0.0, 1.0, width, dtype=np.float32)[None, :]
    y = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
    pixels = np.empty((height, width, 3), dtype=np.float32)
    pixels[:, :, 0] = 30.0 + 190.0 * x
    pixels[:, :, 1] = 40.0 + 160.0 * y
    pixels[:, :, 2] = 70.0 + 120.0 * (1.0 - y)
    stripes = np.sin(np.arange(width, dtype=np.float32) * 0.06)[None, :] * 18.0
    pixels[:, :, 1] += stripes
    return Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8), mode="RGB")


def _adjustments(recipe: str) -> Adjustments:
    if recipe == "neutral":
        return Adjustments()
    full = {
        "exposure_ev": 0.35,
        "contrast": 12.0,
        "highlights": -20.0,
        "shadows": 25.0,
        "temperature": 8.0,
        "tint": -5.0,
        "saturation": 10.0,
        "vibrance": 15.0,
        "clarity": 10.0,
        "sharpen": 20.0,
        "vignette": -15.0,
        "grain": 8.0,
        "rotation_deg": 2.0,
    }
    if recipe == "full_denoise":
        full["denoise"] = 40.0
    return Adjustments(**full)


def _rss_mb() -> float:
    import psutil

    return psutil.Process().memory_info().rss / (1024.0 * 1024.0)


def run_export(megapixels: float, recipe: str) -> int:
    import psutil

    width = round(math.sqrt(megapixels * 1_000_000.0 * 3.0 / 2.0))
    height = round(width * 2.0 / 3.0)
    adjustments = _adjustments(recipe)
    with tempfile.TemporaryDirectory(prefix="frame-ai-repro-export-") as directory:
        path = Path(directory) / "source.jpg"
        _make_source(width, height).save(path, format="JPEG", quality=86)
        gc.collect()

        peak = [_rss_mb()]
        stop = threading.Event()

        def sample() -> None:
            while not stop.wait(0.01):
                peak[0] = max(peak[0], _rss_mb())

        sampler = threading.Thread(target=sample, daemon=True)
        sampler.start()
        started = time.perf_counter()
        try:
            loaded = load_image(path)
            rendered = render(
                loaded,
                adjustments,
                image_sha256="0" * 64,
                quality="export",
            )
            encoded = encode_image(rendered.rgb, image_format="jpeg", quality=92)
        finally:
            stop.set()
            sampler.join(timeout=2)
        elapsed = time.perf_counter() - started

    megabytes = width * height / 1_000_000.0
    print(f"source: {width}x{height} ({megabytes:.1f} MP), recipe: {recipe}")
    print(f"output: {rendered.width}x{rendered.height}, {len(encoded) / 1024:.0f} KiB")
    print(f"elapsed: {elapsed:.1f} s")
    print(f"peak RSS: {peak[0]:.0f} MB ({(peak[0]) / megabytes:.0f} MB/MP)")
    print(
        f"process baseline RSS: {psutil.Process().memory_info().rss / 1024 / 1024:.0f} MB"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("rotation", help="check R2-01 inscribed rotation")
    subparsers.add_parser("icc", help="check R2-02 embedded ICC conversion")
    export_parser = subparsers.add_parser("export", help="measure R2-03 export cost")
    export_parser.add_argument("--mp", type=float, default=24.0)
    export_parser.add_argument(
        "--recipe", choices=("neutral", "full", "full_denoise"), default="full"
    )
    args = parser.parse_args(argv)

    if args.command == "rotation":
        return check_rotation()
    if args.command == "icc":
        return check_icc()
    return run_export(args.mp, args.recipe)


if __name__ == "__main__":
    raise SystemExit(main())
