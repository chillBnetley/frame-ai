from __future__ import annotations

import numpy as np
import pytest

from app.imaging.blend import blend_channels, composite_layer

BASE = np.array([[[0.0, 0.0, 0.0], [0.5, 0.5, 0.5], [1.0, 1.0, 1.0]]], dtype=np.float32)
ADJUSTED = np.array([[[0.0, 0.25, 1.0], [0.5, 0.5, 0.5], [1.0, 0.75, 0.0]]], dtype=np.float32)


def test_normal_is_the_adjusted_colour():
    np.testing.assert_array_equal(blend_channels(BASE, ADJUSTED, "normal"), ADJUSTED)


def test_multiply_screen_and_overlay_math_at_boundaries():
    multiply = blend_channels(BASE, ADJUSTED, "multiply")
    screen = blend_channels(BASE, ADJUSTED, "screen")
    overlay = blend_channels(BASE, ADJUSTED, "overlay")

    np.testing.assert_allclose(multiply, BASE * ADJUSTED, atol=1e-7)
    np.testing.assert_allclose(screen, 1.0 - (1.0 - BASE) * (1.0 - ADJUSTED), atol=1e-7)
    expected_overlay = np.where(
        BASE <= 0.5,
        2.0 * BASE * ADJUSTED,
        1.0 - 2.0 * (1.0 - BASE) * (1.0 - ADJUSTED),
    )
    np.testing.assert_allclose(overlay, expected_overlay, atol=1e-7)
    for output in (multiply, screen, overlay):
        assert output.dtype == np.float32
        assert np.isfinite(output).all()
        assert output.min() >= 0.0 and output.max() <= 1.0


def test_overlay_uses_the_lower_branch_at_half():
    base = np.array([[[0.5, 0.5, 0.5]]], dtype=np.float32)
    adjusted = np.array([[[0.4, 0.8, 1.0]]], dtype=np.float32)

    output = blend_channels(base, adjusted, "overlay")

    np.testing.assert_allclose(output, np.array([[[0.4, 0.8, 1.0]]], dtype=np.float32))


def test_non_normal_modes_clip_the_adjusted_colour_first():
    base = np.array([[[0.5, 0.5, 0.5]]], dtype=np.float32)
    adjusted = np.array([[[2.0, -1.0, 0.5]]], dtype=np.float32)

    output = blend_channels(base, np.clip(adjusted, 0.0, 1.0), "multiply")

    np.testing.assert_allclose(output, np.array([[[0.5, 0.0, 0.25]]], dtype=np.float32))


@pytest.mark.parametrize("mode", ["normal", "multiply", "screen", "overlay"])
def test_composite_edges_opacity_and_masks(mode: str):
    base = np.full((2, 2, 3), 0.2, dtype=np.float32)
    adjusted = np.full((2, 2, 3), 0.8, dtype=np.float32)

    zero = composite_layer(base, adjusted, 0.0, mode)
    one = composite_layer(base, adjusted, np.ones((2, 2, 1), dtype=np.float32), mode)
    half = composite_layer(base, adjusted, np.full((2, 2, 1), 0.5, dtype=np.float32), mode)

    np.testing.assert_array_equal(zero, base)
    full_blend = blend_channels(base, adjusted, mode)
    np.testing.assert_allclose(one, full_blend, atol=1e-7)
    np.testing.assert_allclose(half, (base + full_blend) / 2.0, atol=1e-7)
    for output in (zero, one, half):
        assert output.dtype == np.float32
        assert np.isfinite(output).all()
        assert output.min() >= 0.0 and output.max() <= 1.0


def test_composite_normal_is_linear_in_the_weight():
    base = np.zeros((1, 1, 3), dtype=np.float32)
    adjusted = np.ones((1, 1, 3), dtype=np.float32)

    np.testing.assert_allclose(composite_layer(base, adjusted, 0.25, "normal"), 0.25)
    np.testing.assert_allclose(composite_layer(base, adjusted, 1.0, "normal"), 1.0)


def test_unknown_blend_mode_is_rejected():
    with pytest.raises(ValueError):
        blend_channels(BASE, ADJUSTED, "difference")
