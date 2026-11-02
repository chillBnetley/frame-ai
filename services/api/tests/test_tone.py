from __future__ import annotations

import numpy as np
import pytest

from app.imaging.tone import (
    apply_contrast,
    apply_exposure,
    apply_highlights_shadows,
    apply_tone_linear,
    apply_white_balance,
    linear_to_srgb,
    luminance_linear,
    smoothstep,
    srgb_to_linear,
)


def _random_rgb(seed: int = 0, shape: tuple[int, int] = (24, 32)) -> np.ndarray:
    return np.random.default_rng(seed).random((*shape, 3), dtype=np.float32)


def _gradient(values: np.ndarray) -> np.ndarray:
    line = values.reshape(1, values.size, 1).astype(np.float32)
    return np.repeat(np.repeat(line, 6, axis=0), 3, axis=2)


def test_srgb_round_trip_is_accurate():
    values = np.array([0.0, 0.001, 0.04, 0.18, 0.5, 1.0], dtype=np.float32)

    converted = linear_to_srgb(srgb_to_linear(values.reshape(1, -1, 1)))

    assert np.allclose(converted.reshape(-1), values, atol=1e-6)


def test_neutral_tone_operations_are_identity():
    rgb = _random_rgb()

    assert apply_exposure(rgb, 0) is rgb
    assert apply_white_balance(rgb, 0, 0) is rgb
    assert apply_highlights_shadows(rgb, 0, 0, mask_sigma=1.0) is rgb
    assert (
        apply_tone_linear(
            rgb,
            exposure_ev=0,
            temperature=0,
            tint=0,
            highlights=0,
            shadows=0,
        )
        is rgb
    )


def test_plus_one_ev_doubles_linear_luminance():
    rgb = np.random.default_rng(1).uniform(0.02, 0.3, (10, 12, 3)).astype(np.float32)
    before = luminance_linear(rgb)

    after = apply_exposure(rgb, 1.0)

    assert np.allclose(luminance_linear(after), before * 2.0, rtol=1e-6, atol=1e-7)


def test_white_balance_preserves_luminance_and_shifts_channels():
    rgb = _random_rgb(2)
    before = luminance_linear(rgb)
    red_blue_before = float(rgb[..., 0].mean() / rgb[..., 2].mean())

    adjusted = apply_white_balance(rgb, temperature=60, tint=0)

    assert np.allclose(luminance_linear(adjusted), before, rtol=1e-5, atol=1e-7)
    assert float(adjusted[..., 0].mean() / adjusted[..., 2].mean()) > red_blue_before

    magenta = apply_white_balance(rgb, temperature=0, tint=80)
    assert float(magenta[..., 1].mean() / magenta[..., 0].mean()) < float(
        rgb[..., 1].mean() / rgb[..., 0].mean()
    )


def test_highlights_and_shadows_affect_the_expected_end():
    ramp = _gradient(np.linspace(0.02, 0.85, 256))
    quarter = ramp.shape[1] // 4
    dark_before = float(ramp[:, :quarter].mean())
    bright_before = float(ramp[:, -quarter:].mean())

    darker_highlights = apply_highlights_shadows(ramp, highlights=-100, shadows=0, mask_sigma=2.0)
    assert float(darker_highlights[:, -quarter:].mean()) < bright_before * 0.9
    assert float(darker_highlights[:, :quarter].mean()) == pytest.approx(dark_before, abs=1e-3)

    brighter_shadows = apply_highlights_shadows(ramp, highlights=0, shadows=100, mask_sigma=2.0)
    assert float(brighter_shadows[:, :quarter].mean()) > dark_before * 1.1
    assert float(brighter_shadows[:, -quarter:].mean()) == pytest.approx(bright_before, abs=1e-3)

    brighter_highlights = apply_highlights_shadows(ramp, highlights=100, shadows=0, mask_sigma=2.0)
    assert float(brighter_highlights[:, -quarter:].mean()) > bright_before

    darker_shadows = apply_highlights_shadows(ramp, highlights=0, shadows=-100, mask_sigma=2.0)
    assert float(darker_shadows[:, :quarter].mean()) < dark_before


@pytest.mark.parametrize("contrast", [-100, -50, 0, 50, 100])
def test_contrast_curve_is_monotonic(contrast: float):
    ramp = _gradient(np.linspace(0.0, 1.0, 512))

    adjusted = apply_contrast(ramp, contrast)
    gray = adjusted[0, :, 0]

    assert np.all(np.diff(gray) >= -1e-7)
    assert gray[0] == pytest.approx(0.0, abs=1e-6)
    assert gray[-1] == pytest.approx(1.0, abs=1e-6)


def test_contrast_neutral_is_identity_and_positive_increases_spread():
    ramp = _gradient(np.linspace(0.0, 1.0, 256))

    assert apply_contrast(ramp, 0) is ramp
    neutral_spread = float(ramp[0, :, 0].std())
    contrasted_spread = float(apply_contrast(ramp, 60)[0, :, 0].std())

    assert contrasted_spread > neutral_spread


def test_contrast_does_not_shift_gray_hue():
    gray = np.full((4, 4, 3), 0.35, dtype=np.float32)

    adjusted = apply_contrast(gray, 40)

    assert np.allclose(adjusted[..., 0], adjusted[..., 1], atol=1e-7)
    assert np.allclose(adjusted[..., 1], adjusted[..., 2], atol=1e-7)


def test_smoothstep_clamps_and_interpolates():
    x = np.array([0.0, 0.25, 0.5, 0.75, 1.0], dtype=np.float32)
    result = smoothstep(x, 0.0, 1.0)

    assert result[0] == 0
    assert result[-1] == 1
    assert result[2] == pytest.approx(0.5)
    assert np.all(np.diff(result) >= 0)
