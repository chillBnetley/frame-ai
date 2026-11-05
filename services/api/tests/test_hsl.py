from __future__ import annotations

import colorsys

import numpy as np
import pytest

from app.imaging import hsl as hsl_imaging
from app.imaging.hsl import apply_hsl
from app.imaging.params_map import HSL_BAND_HUES, HSL_HUE_MIN_SLOPE
from app.models.recipe import HSL_BANDS, HslAdjustments, HslBand


def _pixel(hue: float, *, saturation: float = 1.0, lightness: float = 0.5) -> np.ndarray:
    rgb = colorsys.hls_to_rgb((hue % 360.0) / 360.0, lightness, saturation)
    return np.array([[rgb]], dtype=np.float32)


def _hue(rgb: np.ndarray) -> float:
    red, green, blue = (float(channel) for channel in rgb[0, 0])
    hue, _, _ = colorsys.rgb_to_hls(red, green, blue)
    return hue * 360.0


def _saturation(rgb: np.ndarray) -> float:
    red, green, blue = (float(channel) for channel in rgb[0, 0])
    _, _, saturation = colorsys.rgb_to_hls(red, green, blue)
    return saturation


def _circular_difference(first: float, second: float) -> float:
    difference = abs(first - second) % 360.0
    return min(difference, 360.0 - difference)


def test_neutral_hsl_is_an_identity():
    rgb = np.random.default_rng(3).random((5, 4, 3), dtype=np.float32)

    assert apply_hsl(rgb, HslAdjustments()) is rgb


def test_achromatic_pixels_are_untouched():
    grays = np.array([[0.0, 0.2, 0.5], [0.75, 0.93, 1.0]], dtype=np.float32)
    rgb = np.repeat(grays[..., None], 3, axis=-1)
    hsl = HslAdjustments(red=HslBand(hue=60, saturation=-100, luminance=100))

    result = apply_hsl(rgb, hsl)

    assert np.array_equal(result, rgb)


def test_near_neutral_tone_gate_keeps_saturation_and_luminance_responsive():
    # Chroma 0.05 sits above the tone gate (0.005-0.03) but only part-way through
    # the hue gate (0.02-0.10): saturation/luminance act fully, hue stays damped.
    near_neutral = np.array([[[0.525, 0.475, 0.475]]], dtype=np.float32)
    assert float(near_neutral.max() - near_neutral.min()) == pytest.approx(0.05)
    assert _hue(near_neutral) == pytest.approx(0.0)

    desaturated = apply_hsl(near_neutral, HslAdjustments(red=HslBand(saturation=-100)))
    assert float(desaturated.max() - desaturated.min()) < 1e-6

    brightened = apply_hsl(near_neutral, HslAdjustments(red=HslBand(luminance=40)))
    assert float(brightened.mean()) > 0.6

    shifted = apply_hsl(near_neutral, HslAdjustments(red=HslBand(hue=40)))
    assert 0.0 < _circular_difference(_hue(shifted), 0.0) < 25.0


def test_band_adjustments_are_isolated_at_band_centers():
    green = _pixel(120)

    untouched = apply_hsl(
        green,
        HslAdjustments(blue=HslBand(hue=40, saturation=60, luminance=40)),
    )
    assert np.array_equal(untouched, green)

    shifted = apply_hsl(green, HslAdjustments(green=HslBand(hue=30)))
    assert _hue(shifted) == pytest.approx(150.0, abs=0.5)


def test_hue_shift_direction_follows_the_color_wheel():
    red = _pixel(0)
    red_forward = apply_hsl(red, HslAdjustments(red=HslBand(hue=60)))
    red_back = apply_hsl(red, HslAdjustments(red=HslBand(hue=-60)))

    assert 0.0 < _hue(red_forward) <= 60.0
    assert 300.0 < _hue(red_back) < 360.0
    assert float(red_forward[0, 0, 1]) > float(red[0, 0, 1])
    assert float(red_back[0, 0, 0]) > float(red_back[0, 0, 1])

    blue = _pixel(240)
    blue_forward = apply_hsl(blue, HslAdjustments(blue=HslBand(hue=30)))
    blue_back = apply_hsl(blue, HslAdjustments(blue=HslBand(hue=-30)))

    assert 240.0 < _hue(blue_forward) <= 270.0
    assert float(blue_forward[0, 0, 0]) > float(blue[0, 0, 0])
    assert 210.0 <= _hue(blue_back) < 240.0
    assert float(blue_back[0, 0, 1]) > float(blue[0, 0, 1])


def test_saturation_endpoint_removes_and_doubles_color():
    red = _pixel(0)
    gray = apply_hsl(red, HslAdjustments(red=HslBand(saturation=-100)))

    assert gray[0, 0] == pytest.approx([0.5, 0.5, 0.5], abs=1e-6)

    muted = _pixel(0, saturation=0.25)
    boosted = apply_hsl(muted, HslAdjustments(red=HslBand(saturation=100)))

    assert _saturation(boosted) == pytest.approx(0.5, abs=1e-3)
    assert _hue(boosted) == pytest.approx(0.0, abs=0.5)


def test_luminance_factor_brightens_and_darkens():
    red = _pixel(0)

    brighter = apply_hsl(red, HslAdjustments(red=HslBand(luminance=100)))
    darker = apply_hsl(red, HslAdjustments(red=HslBand(luminance=-100)))

    assert brighter[0, 0] == pytest.approx([1.0, 1.0, 1.0], abs=1e-6)
    assert darker[0, 0] == pytest.approx([0.5, 0.0, 0.0], abs=1e-6)


def _hues_of(rgb: np.ndarray) -> np.ndarray:
    """Independent Rec.709-free HSL hue read-back (float64) for ramp analysis."""
    work = rgb.astype(np.float64)
    maximum = np.max(work, axis=-1)
    minimum = np.min(work, axis=-1)
    delta = maximum - minimum
    red, green, blue = work[..., 0], work[..., 1], work[..., 2]

    is_red = maximum == red
    is_green = (maximum == green) & ~is_red
    is_blue = ~is_red & ~is_green
    safe = np.where(delta == 0.0, 1.0, delta)

    hue = np.zeros_like(maximum)
    hue[is_red] = np.mod((green[is_red] - blue[is_red]) / safe[is_red], 6.0)
    hue[is_green] = (blue[is_green] - red[is_green]) / safe[is_green] + 2.0
    hue[is_blue] = (red[is_blue] - green[is_blue]) / safe[is_blue] + 4.0
    return np.where(delta == 0.0, 0.0, hue * 60.0 % 360.0)


def _hue_ramp(*, step: float = 0.25) -> np.ndarray:
    return np.concatenate([_pixel(float(hue)) for hue in np.arange(0.0, 360.0, step)], axis=0)


def _unwrap(hues: np.ndarray) -> np.ndarray:
    lifted = np.asarray(hues, dtype=np.float64).copy()
    for index in range(1, lifted.size):
        while lifted[index] < lifted[index - 1] - 180.0:
            lifted[index] += 360.0
        while lifted[index] > lifted[index - 1] + 180.0:
            lifted[index] -= 360.0
    return lifted


@pytest.mark.parametrize("band", list(HSL_BANDS))
@pytest.mark.parametrize("shift", [-180.0, 180.0])
def test_hue_mapping_never_folds_the_color_wheel(band: str, shift: float):
    ramp = _hue_ramp()
    result = apply_hsl(ramp, HslAdjustments(**{band: HslBand(hue=shift)}))

    lifted = _unwrap(_hues_of(result[:, 0]))
    steps = np.diff(lifted)

    assert np.all(np.isfinite(lifted))
    assert float(steps.min()) >= -1e-6
    assert 350.0 < lifted[-1] - lifted[0] <= 360.0
    assert float(steps.max()) <= 2.5


@pytest.mark.parametrize("band", list(HSL_BANDS))
@pytest.mark.parametrize("shift", [-180.0, 180.0])
def test_extreme_hue_shifts_keep_pixels_valid(band: str, shift: float):
    rgb = np.random.default_rng(4).random((16, 16, 3), dtype=np.float32)

    result = apply_hsl(rgb, HslAdjustments(**{band: HslBand(hue=shift)}))

    assert np.all(np.isfinite(result))
    assert float(result.min()) >= 0.0
    assert float(result.max()) <= 1.0


def test_hue_mapping_is_periodic_across_the_seam():
    hsl = HslAdjustments(red=HslBand(hue=180), blue=HslBand(hue=-90))

    before = _hue(apply_hsl(_pixel(359.9), hsl))
    after = _hue(apply_hsl(_pixel(0.1), hsl))

    assert _circular_difference(before, after) < 0.5


def test_small_hue_shift_matches_the_direct_formula():
    ramp = _hue_ramp()
    samples = np.arange(0.0, 360.0, 0.25, dtype=np.float32)

    for shift in (10.0, -10.0, 5.0, -5.0):
        hsl = HslAdjustments(yellow=HslBand(hue=shift))
        params = hsl_imaging._parameters(hsl)[0]
        expected = np.mod(
            samples + hsl_imaging._mix(params, *hsl_imaging._band_mix(samples)), 360.0
        )

        actual = _hues_of(apply_hsl(ramp, hsl)[:, 0])

        difference = np.abs(actual - expected.astype(np.float64))
        # Below the fold threshold the limiter is a no-op, so only LUT interpolation
        # rounding separates the two; a looser bound would hide a real behaviour change.
        assert float(np.minimum(difference, 360.0 - difference).max()) <= 0.05


def test_neutral_pixels_ignore_even_an_extreme_hue_shift():
    rgb = np.array([[[0.0, 0.0, 0.0], [0.35, 0.35, 0.35], [1.0, 1.0, 1.0]]], dtype=np.float32)

    result = apply_hsl(rgb, HslAdjustments(green=HslBand(hue=180)))

    assert np.array_equal(result, rgb)


def test_hue_wrap_stays_continuous_across_zero():
    hsl = HslAdjustments(red=HslBand(hue=30))

    before = _hue(apply_hsl(_pixel(359), hsl))
    middle = _hue(apply_hsl(_pixel(0), hsl))
    after = _hue(apply_hsl(_pixel(1), hsl))

    assert before < middle < after
    assert _circular_difference(before, after) < 2.5
    assert _circular_difference(middle, 0.0) <= 30.0


def test_skin_tones_blend_without_reversing():
    hsl = HslAdjustments(red=HslBand(hue=60), orange=HslBand(hue=0))
    skin_hues = [10.0, 15.0, 20.0, 25.0, 30.0]

    out = [_hue(apply_hsl(_pixel(hue, saturation=0.8, lightness=0.6), hsl)) for hue in skin_hues]

    assert np.all(np.diff(out) > 0)
    for hue, shifted in zip(skin_hues, out, strict=True):
        assert hue < shifted <= hue + 60.0
    assert _hue(apply_hsl(_pixel(120), hsl)) == pytest.approx(120.0, abs=0.05)
    assert _hue(apply_hsl(_pixel(240), hsl)) == pytest.approx(240.0, abs=0.05)


def test_a_family_rotates_without_crushing_its_own_spacing():
    hsl = HslAdjustments(red=HslBand(hue=60), orange=HslBand(hue=60))

    red_out = _hue(apply_hsl(_pixel(0), hsl))
    orange_out = _hue(apply_hsl(_pixel(30), hsl))
    magenta_out = _hue(apply_hsl(_pixel(330), hsl))
    green_out = _hue(apply_hsl(_pixel(150), hsl))

    assert red_out > 20.0 and orange_out > 50.0
    assert orange_out - red_out == pytest.approx(30.0, abs=0.5)
    assert 0.0 < magenta_out - 330.0 < red_out - 0.0
    assert green_out == pytest.approx(150.0, abs=0.05)


@pytest.mark.parametrize("band", list(HSL_BANDS))
@pytest.mark.parametrize("shift", [-180.0, 180.0])
def test_limited_shifts_leave_the_slope_budget_intact(band: str, shift: float):
    hsl = HslAdjustments(**{band: HslBand(hue=shift)})

    shifts = hsl_imaging._limit_hue_shifts(hsl_imaging._parameters(hsl)[0]).astype(np.float64)

    centers = np.asarray(HSL_BAND_HUES, dtype=np.float64)
    for index in range(centers.size):
        other = (index + 1) % centers.size
        gap = (centers[other] - centers[index]) % 360.0
        peak_slope = abs(shifts[index] - shifts[other]) * 1.5 / gap
        assert peak_slope <= 1.0 - HSL_HUE_MIN_SLOPE + 1e-6


def test_extreme_parameters_remain_finite_and_bounded():
    rgb = np.random.default_rng(7).random((32, 32, 3), dtype=np.float32)
    rgb[0, 0] = (0.0, 0.0, 0.0)
    rgb[0, 1] = (1.0, 1.0, 1.0)
    hsl = HslAdjustments(
        red=HslBand(hue=180, saturation=100, luminance=100),
        orange=HslBand(hue=-180, saturation=-100, luminance=-100),
        yellow=HslBand(hue=90, saturation=100, luminance=-100),
        green=HslBand(hue=-90, saturation=-100, luminance=100),
        aqua=HslBand(hue=45, saturation=80, luminance=-80),
        blue=HslBand(hue=-45, saturation=-80, luminance=80),
        purple=HslBand(hue=120, saturation=60, luminance=-60),
        magenta=HslBand(hue=-120, saturation=-60, luminance=60),
    )

    result = apply_hsl(rgb, hsl)

    assert np.all(np.isfinite(result))
    assert float(result.min()) >= 0.0
    assert float(result.max()) <= 1.0


def test_chunked_processing_matches_a_single_pass(monkeypatch):
    rgb = np.random.default_rng(11).random((23, 19, 3), dtype=np.float32)
    hsl = HslAdjustments(green=HslBand(hue=25, saturation=-40, luminance=15))

    monkeypatch.setattr(hsl_imaging, "HSL_CHUNK_PIXELS", 7)
    chunked = apply_hsl(rgb, hsl)
    monkeypatch.setattr(hsl_imaging, "HSL_CHUNK_PIXELS", 10_000)
    whole = apply_hsl(rgb, hsl)

    assert np.array_equal(chunked, whole)


def test_apply_hsl_does_not_mutate_the_input():
    rgb = _pixel(210, saturation=0.7, lightness=0.4)
    original = rgb.copy()

    apply_hsl(rgb, HslAdjustments(aqua=HslBand(hue=20, saturation=30, luminance=-20)))

    assert np.array_equal(rgb, original)


def test_non_finite_input_does_not_raise():
    rgb = np.array([[[np.nan, 0.5, np.inf], [-np.inf, 0.1, 0.9]]], dtype=np.float32)

    result = apply_hsl(
        rgb,
        HslAdjustments(aqua=HslBand(hue=20, saturation=30, luminance=-20)),
    )

    assert result.shape == rgb.shape
    assert result.dtype == np.float32
