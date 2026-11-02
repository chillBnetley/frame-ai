from __future__ import annotations

import numpy as np
import pytest

from app.imaging.geometry import (
    apply_geometry,
    crop_pixels,
    inscribed_scale,
    rotate_inscribed,
)
from app.models.recipe import Crop

SIZES = [(320, 200), (200, 320), (240, 240)]
ANGLES = [0.0, 0.25, -0.25, 7.5, -7.5, 15.0, -15.0]


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

    result = apply_geometry(rgb, rotation_deg=15.0, crop=crop)

    scale = inscribed_scale(100, 80, 15.0)
    rotated_width = round(100 * scale)
    rotated_height = round(80 * scale)
    assert abs(result.shape[1] - round(rotated_width * 0.5)) <= 1
    assert abs(result.shape[0] - round(rotated_height * 0.5)) <= 1
