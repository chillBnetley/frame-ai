from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.imaging.geometry import (
    apply_geometry,
    canvas_size,
    crop_pixels,
    export_target_size,
    inscribed_scale,
    resize_exact,
    resize_exact_alpha,
    rotate_inscribed,
)
from app.models.recipe import Crop

SIZES = [(320, 200), (200, 320), (240, 240)]
ANGLES = [0.0, 0.25, -0.25, 7.5, -7.5, 15.0, -15.0]
OUTSIDE_SIZES = SIZES + [(2000, 500), (160, 100)]
OUTSIDE_ANGLES = [0.25, 3.0, 7.5, 15.0, -15.0]


@pytest.mark.parametrize("width,height", SIZES)
@pytest.mark.parametrize("angle", ANGLES)
def test_rotation_uses_the_inscribed_dimensions(width: int, height: int, angle: float):
    rgb = np.ones((height, width, 3), dtype=np.float32)
    scale = inscribed_scale(width, height, angle)
    expected_width = max(1, round(width * scale))
    expected_height = max(1, round(height * scale))

    rotated = rotate_inscribed(rgb, angle)

    assert abs(rotated.shape[1] - expected_width) <= 1
    assert abs(rotated.shape[0] - expected_height) <= 1
    assert rotated.dtype == np.float32
    assert float(rotated.min()) > 1.0 - 1e-5
    assert float(rotated.max()) <= 1.0 + 1e-5


@pytest.mark.parametrize("width,height", OUTSIDE_SIZES)
@pytest.mark.parametrize("angle", OUTSIDE_ANGLES)
@pytest.mark.parametrize("quality", ["draft", "final"])
def test_rotation_never_samples_outside_the_source(
    width: int,
    height: int,
    angle: float,
    quality: str,
    monkeypatch: pytest.MonkeyPatch,
):
    # Mirror padding hides out-of-source sampling; constant padding exposes it.
    monkeypatch.setattr(cv2, "BORDER_REFLECT_101", cv2.BORDER_CONSTANT)
    rgb = np.ones((height, width, 3), dtype=np.float32)

    out = rotate_inscribed(rgb, angle, quality=quality)  # type: ignore[arg-type]

    assert float((out.min(axis=2) < 0.5).mean()) == 0.0
    assert float(out.min()) > 0.75


def test_rotation_keeps_content_scale():
    height, width = 600, 900
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    source = np.stack([xx / width, yy / height, np.zeros_like(xx)], axis=-1)

    out = rotate_inscribed(source, 10.0, quality="final")

    row = out[out.shape[0] // 2, :, :2]
    assert float(np.hypot(*(row[-1] - row[0]))) <= 1.0


def test_zero_rotation_is_a_noop():
    rgb = np.random.default_rng(0).random((40, 60, 3), dtype=np.float32)

    assert rotate_inscribed(rgb, 0.0) is rgb


def test_crop_uses_rounded_pixel_rectangles():
    rgb = np.random.default_rng(1).random((80, 100, 3), dtype=np.float32)
    crop = Crop(x=0.1, y=0.2, w=0.5, h=0.4)

    cropped = crop_pixels(rgb, crop)

    assert np.array_equal(cropped, rgb[16:48, 10:60])


@pytest.mark.parametrize(
    "crop,expected",
    [
        (Crop(x=0.0, y=0.0, w=1.0, h=1.0), (100, 80)),
        (Crop(x=0.5, y=0.0, w=0.5, h=1.0), (50, 80)),
        (Crop(x=0.0, y=0.5, w=1.0, h=0.5), (100, 40)),
        (Crop(x=0.99, y=0.99, w=0.01, h=0.01), (1, 1)),
        (Crop(x=0.0, y=0.0, w=0.5, h=0.5), (50, 40)),
    ],
)
def test_crop_boundaries_keep_at_least_one_pixel(crop: Crop, expected: tuple[int, int]):
    rgb = np.ones((80, 100, 3), dtype=np.float32)

    cropped = crop_pixels(rgb, crop)

    assert (cropped.shape[1], cropped.shape[0]) == expected


def test_full_frame_crop_matches_no_crop():
    rgb = np.random.default_rng(2).random((30, 40, 3), dtype=np.float32)

    assert crop_pixels(rgb, None) is rgb
    assert np.array_equal(crop_pixels(rgb, Crop(x=0, y=0, w=1, h=1)), rgb)


def test_geometry_applies_rotation_before_crop():
    rgb = np.ones((80, 100, 3), dtype=np.float32)
    crop = Crop(x=0.25, y=0.25, w=0.5, h=0.5)

    result, alpha = apply_geometry(rgb, rotation_deg=15.0, crop=crop)

    assert alpha is None
    scale = inscribed_scale(100, 80, 15.0)
    rotated_width = round(100 * scale)
    rotated_height = round(80 * scale)
    assert abs(result.shape[1] - round(rotated_width * 0.5)) <= 1
    assert abs(result.shape[0] - round(rotated_height * 0.5)) <= 1


@pytest.mark.parametrize("width,height", SIZES)
@pytest.mark.parametrize("angle", ANGLES)
def test_canvas_size_matches_the_rendered_geometry(width: int, height: int, angle: float):
    rgb = np.ones((height, width, 3), dtype=np.float32)

    rotated = rotate_inscribed(rgb, angle)

    assert canvas_size(width, height, angle, None) == (
        rotated.shape[1],
        rotated.shape[0],
    )


def test_canvas_size_applies_crop_after_rotation():
    crop = Crop(x=0.25, y=0.25, w=0.5, h=0.5)
    rgb = np.ones((80, 100, 3), dtype=np.float32)

    cropped, _ = apply_geometry(rgb, rotation_deg=15.0, crop=crop)

    assert canvas_size(100, 80, 15.0, crop) == (cropped.shape[1], cropped.shape[0])


def test_export_target_without_max_edge_keeps_the_full_canvas():
    width, height, scale = export_target_size(1000, 600, 7.5, None, None)

    assert (width, height) == canvas_size(1000, 600, 7.5, None)
    assert scale == 1.0


@pytest.mark.parametrize("max_edge", [1200, 1000])
def test_export_target_never_upscales(max_edge: int):
    canvas_width, canvas_height = canvas_size(1000, 600, 0.0, None)

    width, height, scale = export_target_size(1000, 600, 0.0, None, max_edge)

    assert (width, height) == (canvas_width, canvas_height)
    assert scale == 1.0


def test_export_target_just_below_the_canvas_downscales_by_one_pixel():
    width, height, scale = export_target_size(1000, 600, 0.0, None, 999)

    assert (width, height) == (999, 599)
    assert scale == pytest.approx(999 / 1000)


@pytest.mark.parametrize(
    ("size", "angle", "crop", "max_edge"),
    [
        ((1000, 600), 0.0, None, 500),
        ((1000, 600), 7.5, None, 500),
        ((1000, 600), -7.5, Crop(x=0.1, y=0.2, w=0.7, h=0.6), 480),
        ((600, 1000), 15.0, Crop(x=0.0, y=0.0, w=0.5, h=1.0), 240),
        ((321, 997), 3.0, Crop(x=0.25, y=0.05, w=0.5, h=0.9), 64),
    ],
)
def test_export_target_long_edge_is_exact(
    size: tuple[int, int],
    angle: float,
    crop: Crop | None,
    max_edge: int,
):
    width, height, scale = export_target_size(size[0], size[1], angle, crop, max_edge)

    assert max(width, height) == max_edge
    canvas_width, canvas_height = canvas_size(size[0], size[1], angle, crop)
    assert scale == max_edge / max(canvas_width, canvas_height)
    assert abs(width / height - canvas_width / canvas_height) < 0.02


def test_resize_exact_preserves_dtype_and_is_a_noop_for_matching_size():
    float_pixels = np.ones((40, 60, 3), dtype=np.float32)
    byte_pixels = np.zeros((40, 60, 3), dtype=np.uint8)

    assert resize_exact(float_pixels, 60, 40) is float_pixels
    downscaled = resize_exact(float_pixels, 30, 20)
    upscaled = resize_exact(byte_pixels, 90, 60)

    assert downscaled.shape == (20, 30, 3)
    assert downscaled.dtype == np.float32
    assert upscaled.shape == (60, 90, 3)
    assert upscaled.dtype == np.uint8


def test_resize_exact_of_a_gradient_stays_in_range():
    ramp = np.repeat((np.arange(64, dtype=np.float32) / 63.0)[None, :, None], 8, axis=0)
    source = np.dstack([ramp, 1.0 - ramp, np.ones_like(ramp)])

    resized = resize_exact(source, 32, 8)

    assert resized.shape == (8, 32, 3)
    assert float(resized.min()) >= -1e-6
    assert float(resized.max()) <= 1.0 + 1e-6
    assert float(resized[0, -1, 0]) > float(resized[0, 0, 0])


def test_apply_geometry_keeps_alpha_aligned_with_rgb():
    height, width = 90, 130
    rgb = np.random.default_rng(3).random((height, width, 3), dtype=np.float32)
    alpha = np.random.default_rng(4).random((height, width), dtype=np.float32)
    crop = Crop(x=0.1, y=0.2, w=0.7, h=0.6)

    result_rgb, result_alpha = apply_geometry(
        rgb,
        alpha,
        rotation_deg=7.5,
        crop=crop,
    )

    assert result_alpha is not None
    assert result_rgb.shape[:2] == result_alpha.shape
    assert result_rgb.dtype == np.float32
    assert result_alpha.dtype == np.float32
    assert 0.0 <= float(result_alpha.min())
    assert float(result_alpha.max()) <= 1.0
    assert 0.0 <= float(result_rgb.min())
    assert float(result_rgb.max()) <= 1.0


def test_geometry_crop_keeps_transparent_corners_transparent():
    rgb = np.ones((40, 60, 3), dtype=np.float32)
    alpha = np.ones((40, 60), dtype=np.float32)
    alpha[:4, :] = 0.0
    alpha[:, :4] = 0.0
    alpha[-4:, :] = 0.0
    alpha[:, -4:] = 0.0

    result_rgb, result_alpha = apply_geometry(
        rgb,
        alpha,
        rotation_deg=0.0,
        crop=Crop(x=0.0, y=0.0, w=1.0, h=1.0),
    )

    assert result_alpha is not None
    assert result_alpha[0, 0] == 0.0
    assert result_alpha[0, -1] == 0.0
    assert result_alpha[-1, 0] == 0.0
    assert result_alpha[-1, -1] == 0.0
    assert result_alpha[20, 30] == 1.0
    # Fully transparent pixels get deterministic black RGB.
    assert np.all(result_rgb[0, 0] == 0.0)


@pytest.mark.parametrize("quality", ["draft", "final"])
def test_alpha_rotation_does_not_pull_transparent_colour_into_visible_edges(
    quality: str,
):
    # Opaque red left half, transparent green right half. Premultiplied warping
    # must not produce a green fringe along the alpha edge.
    rgb = np.zeros((80, 160, 3), dtype=np.float32)
    rgb[:, :80] = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    rgb[:, 80:] = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    alpha = np.zeros((80, 160), dtype=np.float32)
    alpha[:, :80] = 1.0

    out_rgb, out_alpha = apply_geometry(
        rgb,
        alpha,
        rotation_deg=7.5,
        crop=None,
        quality=quality,  # type: ignore[arg-type]
    )

    assert out_alpha is not None
    visible = out_alpha > 0.25
    assert np.any(visible)
    assert float(out_rgb[visible, 1].max()) < 0.02


def test_resize_exact_alpha_premultiplies_and_preserves_dtype():
    rgb = np.zeros((2, 4, 3), dtype=np.uint8)
    rgb[:, :2] = np.array([255, 0, 0], dtype=np.uint8)
    rgb[:, 2:] = np.array([0, 255, 0], dtype=np.uint8)
    alpha = np.zeros((2, 4), dtype=np.uint8)
    alpha[:, :2] = 255

    resized_rgb, resized_alpha = resize_exact_alpha(rgb, alpha, 2, 1)

    assert resized_rgb.dtype == np.uint8
    assert resized_alpha.dtype == np.uint8
    assert resized_alpha[0, 0] > 200
    assert resized_alpha[0, 1] == 0
    assert resized_rgb[0, 0, 0] > 250
    assert resized_rgb[0, 0, 1] < 5
    same_rgb, same_alpha = resize_exact_alpha(rgb, alpha, 4, 2)
    assert same_rgb is rgb
    assert same_alpha is alpha
