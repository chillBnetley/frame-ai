from __future__ import annotations

from io import BytesIO

import cv2
import numpy as np
import pytest
from PIL import Image

from app.imaging.geometry import inscribed_scale
from app.imaging.loader import load_image
from app.imaging.params_map import DRAFT_MAX_EDGE, FINAL_MAX_EDGE
from app.imaging.pipeline import render, tier_max_edge
from app.models.recipe import Adjustments, Crop
from tests.golden_support import source_bytes

SHA_A = "a" * 64
SHA_B = "b" * 64


def _png_bytes(pixels: np.ndarray) -> bytes:
    buffer = BytesIO()
    Image.fromarray(pixels).save(buffer, format="PNG")
    return buffer.getvalue()


def _synthetic_photo(width: int, height: int) -> np.ndarray:
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    u = x / max(width - 1, 1)
    v = y / max(height - 1, 1)
    red = 0.1 + 0.7 * u
    green = 0.15 + 0.55 * v
    blue = 0.25 + 0.4 * (1.0 - u) + 0.15 * np.sin(3.0 * np.pi * u) * np.cos(2.0 * np.pi * v)
    blob = np.clip(1.0 - np.sqrt((u - 0.55) ** 2 + (v - 0.5) ** 2) / 0.35, 0.0, 1.0)
    blob = blob * blob * (3.0 - 2.0 * blob)
    red = np.clip(red + 0.2 * blob, 0.0, 1.0)
    blue = np.clip(blue - 0.05 * blob, 0.0, 1.0)
    data = np.stack([red, green, blue], axis=-1)
    return np.rint(data * 255.0).astype(np.uint8)


def _load_pixels(pixels: np.ndarray):
    return load_image(_png_bytes(pixels))


def test_neutral_recipe_is_an_identity_render():
    payload = source_bytes("ramp")
    loaded = load_image(payload)

    rendered = render(loaded, Adjustments(), image_sha256=SHA_A, quality="export")

    assert rendered.rgb.dtype == np.uint8
    assert (rendered.width, rendered.height) == (loaded.width, loaded.height)
    difference = np.abs(
        rendered.rgb.astype(np.int16) - np.rint(loaded.rgb * 255.0).astype(np.int16)
    )
    assert int(difference.max()) <= 1


def test_render_tiers_and_explicit_edges():
    assert tier_max_edge("draft") == DRAFT_MAX_EDGE
    assert tier_max_edge("final") == FINAL_MAX_EDGE
    assert tier_max_edge("export") is None

    loaded = _load_pixels(_synthetic_photo(1280, 640))
    adjustments = Adjustments(contrast=10)

    draft = render(loaded, adjustments, image_sha256=SHA_A, quality="draft")
    final = render(loaded, adjustments, image_sha256=SHA_A, quality="final")
    exported = render(loaded, adjustments, image_sha256=SHA_A, quality="export")
    resized = render(
        loaded,
        adjustments,
        image_sha256=SHA_A,
        quality="export",
        max_edge=400,
    )

    assert (draft.width, draft.height) == (960, 480)
    assert (final.width, final.height) == (1280, 640)
    assert (exported.width, exported.height) == (1280, 640)
    assert (resized.width, resized.height) == (400, 200)


def test_large_export_denoise_reports_a_warning():
    loaded = _load_pixels(_synthetic_photo(64, 48))

    simplified = render(
        loaded,
        Adjustments(denoise=50),
        image_sha256=SHA_A,
        quality="export",
        denoise_simplify_pixels=1,
    )
    below_threshold = render(
        loaded,
        Adjustments(denoise=50),
        image_sha256=SHA_A,
        quality="export",
        denoise_simplify_pixels=64 * 48,
    )
    preview = render(
        loaded,
        Adjustments(denoise=50),
        image_sha256=SHA_A,
        quality="final",
        denoise_simplify_pixels=1,
    )
    without_denoise = render(
        loaded,
        Adjustments(),
        image_sha256=SHA_A,
        quality="export",
        denoise_simplify_pixels=1,
    )

    assert simplified.warnings == ("denoise_simplified",)
    assert below_threshold.warnings == ()
    assert preview.warnings == ()
    assert without_denoise.warnings == ()


def test_rotation_and_crop_report_the_rotated_canvas():
    loaded = _load_pixels(_synthetic_photo(200, 120))

    rotated = render(
        loaded,
        Adjustments(rotation_deg=7.5),
        image_sha256=SHA_A,
        quality="export",
    )
    cropped = render(
        loaded,
        Adjustments(rotation_deg=7.5, crop=Crop(x=0.1, y=0.1, w=0.6, h=0.6)),
        image_sha256=SHA_A,
        quality="export",
    )
    unrotated = render(loaded, Adjustments(), image_sha256=SHA_A, quality="export")

    expected_width = max(1, round(loaded.width * inscribed_scale(200, 120, 7.5)))
    expected_height = max(1, round(loaded.height * inscribed_scale(200, 120, 7.5)))
    assert abs(rotated.canvas_width - expected_width) <= 1
    assert abs(rotated.canvas_height - expected_height) <= 1
    assert (rotated.width, rotated.height) == (rotated.canvas_width, rotated.canvas_height)
    assert cropped.canvas_width == rotated.canvas_width
    assert cropped.canvas_height == rotated.canvas_height
    assert cropped.width < rotated.width
    assert cropped.height < rotated.height
    assert (unrotated.canvas_width, unrotated.canvas_height) == (200, 120)


def test_full_frame_crop_matches_no_crop():
    loaded = _load_pixels(_synthetic_photo(120, 80))

    without = render(loaded, Adjustments(), image_sha256=SHA_A, quality="export")
    with_crop = render(
        loaded,
        Adjustments(crop=Crop(x=0.0, y=0.0, w=1.0, h=1.0)),
        image_sha256=SHA_A,
        quality="export",
    )

    assert np.array_equal(without.rgb, with_crop.rgb)


def test_render_is_byte_for_byte_deterministic():
    pixels = _synthetic_photo(320, 240)
    adjustments = Adjustments(
        exposure_ev=0.25,
        contrast=10,
        highlights=-15,
        shadows=20,
        temperature=8,
        saturation=10,
        clarity=25,
        vignette=15,
        denoise=20,
        sharpen=20,
        grain=30,
    )

    first = render(_load_pixels(pixels), adjustments, image_sha256=SHA_A, quality="final")
    second = render(_load_pixels(pixels), adjustments, image_sha256=SHA_A, quality="final")

    assert first.rgb.tobytes() == second.rgb.tobytes()


def test_grain_pattern_only_depends_on_the_original_digest():
    loaded = _load_pixels(_synthetic_photo(160, 120))
    adjustments = Adjustments(grain=40)

    first = render(loaded, adjustments, image_sha256=SHA_A, quality="final")
    same = render(loaded, adjustments, image_sha256=SHA_A, quality="final")
    other = render(loaded, adjustments, image_sha256=SHA_B, quality="final")

    assert np.array_equal(first.rgb, same.rgb)
    assert not np.array_equal(first.rgb, other.rgb)


def test_resolution_invariance_stays_within_three_gray_levels():
    high_pixels = _synthetic_photo(1600, 1200)
    low_pixels = cv2.resize(high_pixels, (800, 600), interpolation=cv2.INTER_AREA)
    adjustments = Adjustments(
        exposure_ev=0.25,
        temperature=12,
        tint=-8,
        highlights=30,
        shadows=25,
        contrast=18,
        saturation=12,
        vibrance=30,
        clarity=30,
        vignette=20,
        sharpen=25,
    )

    high = render(
        _load_pixels(high_pixels),
        adjustments,
        image_sha256=SHA_A,
        quality="export",
        max_edge=1600,
    )
    low = render(
        _load_pixels(low_pixels),
        adjustments,
        image_sha256=SHA_A,
        quality="export",
        max_edge=800,
    )
    downscaled = cv2.resize(
        high.rgb,
        (low.width, low.height),
        interpolation=cv2.INTER_AREA,
    )

    mean_difference = float(
        np.abs(downscaled.astype(np.float32) - low.rgb.astype(np.float32)).mean()
    )
    assert mean_difference <= 3.0


def test_render_rejects_invalid_max_edge():
    loaded = _load_pixels(_synthetic_photo(32, 24))

    with pytest.raises(ValueError):
        render(loaded, Adjustments(), image_sha256=SHA_A, max_edge=0)
