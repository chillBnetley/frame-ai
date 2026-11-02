from __future__ import annotations

import numpy as np
import pytest

from app.imaging.local import apply_clarity, apply_local, apply_vignette, vignette_falloff
from app.imaging.tone import luminance_srgb


def _textured_midtones(size: tuple[int, int] = (72, 96)) -> np.ndarray:
    height, width = size
    pattern = np.indices((height, width)).sum(axis=0) // 8 % 2
    base = np.where(pattern == 0, 0.42, 0.58)
    return np.repeat(base.astype(np.float32)[..., None], 3, axis=2)


def test_neutral_local_operations_are_identity():
    rgb = _textured_midtones()

    assert apply_clarity(rgb, 0) is rgb
    assert apply_vignette(rgb, 0) is rgb
    assert apply_local(rgb, clarity=0, vignette=0) is rgb


def test_positive_clarity_increases_midtone_local_contrast():
    rgb = _textured_midtones()
    before = float(np.std(luminance_srgb(rgb)))

    sharpened = apply_clarity(rgb, 60)
    softened = apply_clarity(rgb, -60)

    assert float(np.std(luminance_srgb(sharpened))) > before
    assert float(np.std(luminance_srgb(softened))) < before
    assert sharpened.dtype == np.float32
    assert 0.0 <= float(sharpened.min())
    assert float(sharpened.max()) <= 1.0


def test_clarity_leaves_flat_areas_untouched():
    rgb = np.full((32, 40, 3), 0.5, dtype=np.float32)

    adjusted = apply_clarity(rgb, 80)

    assert np.allclose(adjusted, rgb, atol=1e-6)


def test_vignette_falloff_is_zero_at_center_and_one_at_corners():
    falloff = vignette_falloff(101, 101)

    assert falloff.shape == (101, 101)
    assert falloff[50, 50] == 0.0
    assert np.isclose(falloff[0, 0], 1.0, atol=1e-5)
    assert np.isclose(falloff[0, -1], 1.0, atol=1e-5)
    assert np.isclose(falloff[-1, 0], 1.0, atol=1e-5)
    assert np.isclose(falloff[-1, -1], 1.0, atol=1e-5)
    assert falloff[50, 80] < falloff[50, 100]


@pytest.mark.parametrize("vignette", [40.0, 100.0])
def test_positive_vignette_darkens_corners_only(vignette: float):
    rgb = np.full((101, 101, 3), 0.5, dtype=np.float32)

    adjusted = apply_vignette(rgb, vignette)

    assert np.allclose(adjusted[50, 50], rgb[50, 50], atol=1e-6)
    assert float(adjusted[0, 0].mean()) < float(adjusted[50, 50].mean())
    assert float(adjusted[-1, -1].mean()) < float(adjusted[50, 50].mean())


def test_negative_vignette_brightens_corners_only():
    rgb = np.full((101, 101, 3), 0.5, dtype=np.float32)

    adjusted = apply_vignette(rgb, -80)

    assert np.allclose(adjusted[50, 50], rgb[50, 50], atol=1e-6)
    assert float(adjusted[0, 0].mean()) > float(adjusted[50, 50].mean())


def test_apply_local_runs_clarity_before_vignette():
    rgb = _textured_midtones()

    assert np.array_equal(
        apply_local(rgb, clarity=35, vignette=25),
        apply_vignette(apply_clarity(rgb, 35), 25),
    )
