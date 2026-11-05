from __future__ import annotations

import colorsys

import numpy as np
import pytest

from app.imaging.tone import (
    apply_contrast,
    apply_exposure,
    apply_highlights_shadows,
    apply_tone_linear,
    apply_white_balance,
    apply_whites_blacks,
    linear_to_srgb,
    luma_srgb,
    luminance_linear,
    smoothstep,
    srgb_to_linear,
    tone_mask_sigma,
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
    assert apply_whites_blacks(rgb, 0, 0, mask_sigma=1.0) is rgb
    assert (
        apply_tone_linear(
            rgb,
            exposure_ev=0,
            temperature=0,
            tint=0,
            highlights=0,
            shadows=0,
            whites=0,
            blacks=0,
        )
        is rgb
    )


def test_plus_one_ev_doubles_linear_luminance():
    rgb = np.random.default_rng(1).uniform(0.02, 0.3, (10, 12, 3)).astype(np.float32)
    before = luminance_linear(rgb)

    after = apply_exposure(rgb, 1.0)

    assert np.allclose(luminance_linear(after), before * 2.0, rtol=1e-6, atol=1e-7)


def _mixed_rgb() -> np.ndarray:
    """Primaries plus near-neutral pixels, as one image would contain."""
    return np.array(
        [
            [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            [[0.3, 0.45, 0.85], [0.5, 0.5, 0.5], [0.9, 0.9, 0.9]],
        ],
        dtype=np.float32,
    )


def _hue_of(pixel: np.ndarray) -> float:
    red, green, blue = (float(channel) for channel in pixel)
    hue, _, _ = colorsys.rgb_to_hls(red, green, blue)
    return hue * 360.0


def test_white_balance_moves_saturated_colors():
    rgb = _mixed_rgb()
    adjusted = apply_white_balance(rgb, temperature=100, tint=0)

    for index in (0, 1, 2):
        before = float(luminance_linear(rgb)[0, index])
        after = float(luminance_linear(adjusted)[0, index])
        assert abs(after - before) > 1e-3

    sky = rgb[1, 0]
    sky_after = adjusted[1, 0]
    assert float(sky_after[0]) > float(sky[0])
    assert float(sky_after[2]) < float(sky[2])

    cooled = apply_white_balance(rgb, temperature=-100, tint=0)
    assert float(cooled[0, 0, 0]) < float(adjusted[0, 0, 0])
    assert float(cooled[0, 2, 2]) > float(adjusted[0, 2, 2])
    assert _hue_of(cooled[1, 0]) > _hue_of(sky) > _hue_of(sky_after)

    magenta = apply_white_balance(rgb, temperature=0, tint=100)
    assert float(magenta[1, 1, 1]) < float(magenta[1, 1, 0])
    assert float(magenta[1, 2, 1]) < float(magenta[1, 2, 2])


def test_white_balance_gain_is_uniform_across_pixels():
    rgb = _mixed_rgb()
    adjusted = apply_white_balance(rgb, temperature=60, tint=-20)

    colored = np.all(rgb > 0.01, axis=-1)
    ratios = adjusted.reshape(-1, 3)[colored.reshape(-1)] / rgb.reshape(-1, 3)[colored.reshape(-1)]

    assert np.allclose(ratios, ratios[0], rtol=1e-6)
    assert float(ratios[0, 0]) > 1.0 > float(ratios[0, 2])
    assert float(ratios[0, 1]) < 1.0


def test_white_balance_preserves_mean_luminance():
    rgb = _random_rgb(2)

    adjusted = apply_white_balance(rgb, temperature=60, tint=0)

    assert float(abs(luminance_linear(adjusted).mean() - luminance_linear(rgb).mean())) < 1e-3
    magenta = apply_white_balance(rgb, temperature=0, tint=80)
    assert float(abs(luminance_linear(magenta).mean() - luminance_linear(rgb).mean())) < 1e-3


def test_white_balance_keeps_black_at_black():
    rgb = _mixed_rgb().copy()
    rgb[1, 1] = (0.0, 0.0, 0.0)

    adjusted = apply_white_balance(rgb, temperature=100, tint=100)

    assert np.array_equal(adjusted[1, 1], np.zeros(3, dtype=np.float32))


def test_white_balance_zero_is_exact_identity():
    rgb = _random_rgb(5)

    assert apply_white_balance(rgb, 0, 0) is rgb


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


def test_positive_blacks_darkens_and_negative_blacks_lifts():
    ramp = _gradient(np.linspace(0.0, 0.85, 256))
    edge = ramp.shape[1] // 32
    dark_before = float(ramp[:, :edge].mean())
    bright_before = float(ramp[:, -edge:].mean())

    # Lightroom/ACR convention: +Blacks raises the black point, darkening shadows.
    darkened_blacks = apply_whites_blacks(ramp, whites=0, blacks=100, mask_sigma=2.0)
    assert float(darkened_blacks[:, :edge].mean()) < dark_before * 0.9
    assert float(darkened_blacks[:, -edge:].mean()) == pytest.approx(bright_before, abs=1e-3)

    lifted_blacks = apply_whites_blacks(ramp, whites=0, blacks=-100, mask_sigma=2.0)
    assert float(lifted_blacks[:, :edge].mean()) > dark_before
    assert float(lifted_blacks[:, -edge:].mean()) == pytest.approx(bright_before, abs=1e-3)

    brighter_whites = apply_whites_blacks(ramp, whites=100, blacks=0, mask_sigma=2.0)
    assert float(brighter_whites[:, -edge:].mean()) > bright_before
    assert float(brighter_whites[:, :edge].mean()) == pytest.approx(dark_before, abs=1e-3)

    darker_whites = apply_whites_blacks(ramp, whites=-100, blacks=0, mask_sigma=2.0)
    assert float(darker_whites[:, -edge:].mean()) < bright_before
    assert float(darker_whites[:, :edge].mean()) == pytest.approx(dark_before, abs=1e-3)


@pytest.mark.parametrize(
    ("whites", "blacks"),
    [(-100, 0), (100, 0), (0, -100), (0, 100), (-100, -100), (100, 100), (-60, 80)],
)
def test_whites_and_blacks_keep_ramps_monotonic(whites: float, blacks: float):
    ramp = srgb_to_linear(_gradient(np.linspace(0.0, 1.0, 512)))

    adjusted = apply_whites_blacks(ramp, whites=whites, blacks=blacks, mask_sigma=0.0)
    gray = linear_to_srgb(np.clip(adjusted, 0.0, 1.0))[0, :, 0]

    assert np.all(np.isfinite(adjusted))
    assert np.all(np.diff(gray) >= -1e-6)
    assert float(np.diff(gray).max()) <= 3.0 / 255.0


def test_whites_and_blacks_preserve_channel_ratios():
    color = np.tile(np.array([0.05, 0.025, 0.0125], dtype=np.float32), (8, 8, 1))
    ratios = color[0, 0] / color[0, 0].sum()

    adjusted = apply_whites_blacks(color, whites=40, blacks=60, mask_sigma=0.0)
    adjusted_ratios = adjusted[0, 0] / adjusted[0, 0].sum()

    assert not np.allclose(adjusted[0, 0], color[0, 0])
    assert np.allclose(adjusted_ratios, ratios, atol=1e-6)


def test_tone_order_is_fixed():
    rgb = _random_rgb(3)
    sigma = tone_mask_sigma(rgb.shape[1], rgb.shape[0])

    expected = apply_exposure(rgb, 0.4)
    expected = apply_white_balance(expected, temperature=25, tint=-10)
    expected = apply_highlights_shadows(expected, highlights=-20, shadows=30, mask_sigma=sigma)
    expected = apply_whites_blacks(expected, whites=15, blacks=-25, mask_sigma=sigma)

    actual = apply_tone_linear(
        rgb,
        exposure_ev=0.4,
        temperature=25,
        tint=-10,
        highlights=-20,
        shadows=30,
        whites=15,
        blacks=-25,
    )

    assert np.allclose(actual, expected, rtol=1e-6, atol=1e-8)

    reordered = apply_whites_blacks(expected, whites=15, blacks=-25, mask_sigma=sigma)
    assert not np.allclose(reordered, expected, rtol=1e-4, atol=1e-6)

    swapped = apply_exposure(rgb, 0.4)
    swapped = apply_white_balance(swapped, temperature=25, tint=-10)
    swapped = apply_whites_blacks(swapped, whites=15, blacks=-25, mask_sigma=sigma)
    swapped = apply_highlights_shadows(swapped, highlights=-20, shadows=30, mask_sigma=sigma)
    assert not np.allclose(swapped, expected, rtol=1e-4, atol=1e-6)


@pytest.mark.parametrize(
    ("overrides", "stage"),
    [
        ({"exposure_ev": 0.7}, lambda rgb, sigma: apply_exposure(rgb, 0.7)),
        (
            {"temperature": 40.0, "tint": -25.0},
            lambda rgb, sigma: apply_white_balance(rgb, 40, -25),
        ),
        (
            {"highlights": -30.0, "shadows": 45.0},
            lambda rgb, sigma: apply_highlights_shadows(rgb, -30, 45, mask_sigma=sigma),
        ),
        (
            {"whites": 20.0, "blacks": -35.0},
            lambda rgb, sigma: apply_whites_blacks(rgb, 20, -35, mask_sigma=sigma),
        ),
    ],
)
def test_each_tone_stage_is_applied_on_its_own(
    overrides: dict[str, float],
    stage,
):
    rgb = _random_rgb(6)
    sigma = tone_mask_sigma(32, 24)
    neutral = {
        "exposure_ev": 0,
        "temperature": 0,
        "tint": 0,
        "highlights": 0,
        "shadows": 0,
        "whites": 0,
        "blacks": 0,
    }

    actual = apply_tone_linear(rgb, **{**neutral, **overrides})

    assert np.allclose(actual, stage(rgb, sigma), rtol=1e-6, atol=1e-8)


def test_extreme_tone_parameters_stay_finite():
    rgb = _random_rgb(4)

    adjusted = apply_tone_linear(
        rgb,
        exposure_ev=5,
        temperature=100,
        tint=-100,
        highlights=100,
        shadows=-100,
        whites=100,
        blacks=-100,
    )

    assert np.all(np.isfinite(adjusted))
    assert float(adjusted.max()) < 1e6


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


@pytest.mark.parametrize("contrast", [-100, -60, 40, 100])
def test_contrast_keeps_chroma_within_five_percent(contrast: float):
    rgb = np.tile(np.array([0.28, 0.18, 0.12], dtype=np.float32), (8, 8, 1))
    source = rgb[0, 0]
    source_chroma = float(source.max() - source.min())
    source_luma = float(luma_srgb(source))

    adjusted = apply_contrast(rgb, contrast)[0, 0]
    chroma = float(adjusted.max() - adjusted.min())
    gray = np.full((1, 1, 3), source_luma, dtype=np.float32)
    expected_luma = float(apply_contrast(gray, contrast)[0, 0, 0])

    assert source_chroma * 0.95 - 1e-6 <= chroma <= source_chroma * 1.05 + 1e-6
    assert float(luma_srgb(adjusted)) == pytest.approx(expected_luma, abs=1e-6)


def test_smoothstep_clamps_and_interpolates():
    x = np.array([0.0, 0.25, 0.5, 0.75, 1.0], dtype=np.float32)
    result = smoothstep(x, 0.0, 1.0)

    assert result[0] == 0
    assert result[-1] == 1
    assert result[2] == pytest.approx(0.5)
    assert np.all(np.diff(result) >= 0)


def test_non_finite_input_does_not_raise():
    rgb = np.array([[[np.nan, 0.5, np.inf], [-np.inf, 0.2, 0.8]]], dtype=np.float32)

    linear = apply_tone_linear(
        rgb,
        exposure_ev=0.5,
        temperature=20,
        tint=5,
        highlights=30,
        shadows=-30,
        whites=10,
        blacks=10,
    )
    result = apply_contrast(linear, 40)

    assert result.shape == rgb.shape
    assert result.dtype == np.float32
