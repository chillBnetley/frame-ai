from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from app.imaging.params_map import (
    HSL_BAND_HUES,
    HSL_CHUNK_PIXELS,
    HSL_HUE_GATE_HIGH,
    HSL_HUE_GATE_LOW,
    HSL_HUE_LIMIT_SWEEPS,
    HSL_HUE_LUT_STEP,
    HSL_HUE_MIN_SLOPE,
    HSL_LUMINANCE_EV,
    HSL_TONE_GATE_HIGH,
    HSL_TONE_GATE_LOW,
)
from app.imaging.tone import smoothstep
from app.models.recipe import HSL_BANDS, HslAdjustments

RgbArray = NDArray[np.float32]
_EPS = np.float32(1e-6)


def _parameters(
    hsl: HslAdjustments,
) -> tuple[NDArray[np.float32], NDArray[np.float32], NDArray[np.float32]]:
    bands = [getattr(hsl, name) for name in HSL_BANDS]
    hue = np.array([band.hue for band in bands], dtype=np.float32)
    saturation = np.array([band.saturation for band in bands], dtype=np.float32)
    luminance = np.array([band.luminance for band in bands], dtype=np.float32)
    return hue, saturation, luminance


def _rgb_to_hsl(
    rgb: RgbArray,
) -> tuple[NDArray[np.float32], NDArray[np.float32], NDArray[np.float32]]:
    maximum = np.max(rgb, axis=-1)
    minimum = np.min(rgb, axis=-1)
    delta = maximum - minimum

    lightness = (maximum + minimum) * np.float32(0.5)
    denominator = np.float32(1.0) - np.abs(lightness * np.float32(2.0) - np.float32(1.0))
    safe_denominator = np.where(denominator > _EPS, denominator, np.float32(1.0))
    saturation = np.where(denominator > _EPS, delta / safe_denominator, np.float32(0.0))

    red = rgb[..., 0]
    green = rgb[..., 1]
    blue = rgb[..., 2]
    safe_delta = np.where(delta > _EPS, delta, np.float32(1.0))
    hue = np.where(
        maximum == red,
        np.mod((green - blue) / safe_delta, np.float32(6.0)),
        np.where(
            maximum == green,
            (blue - red) / safe_delta + np.float32(2.0),
            (red - green) / safe_delta + np.float32(4.0),
        ),
    )
    hue = np.where(
        delta > _EPS,
        np.mod(hue * np.float32(60.0), np.float32(360.0)),
        np.float32(0.0),
    )
    return (
        hue.astype(np.float32, copy=False),
        np.clip(saturation, 0.0, 1.0).astype(np.float32, copy=False),
        np.clip(lightness, 0.0, 1.0).astype(np.float32, copy=False),
    )


def _hsl_to_rgb(
    hue: NDArray[np.float32],
    saturation: NDArray[np.float32],
    lightness: NDArray[np.float32],
) -> RgbArray:
    chroma = (np.float32(1.0) - np.abs(lightness * np.float32(2.0) - np.float32(1.0))) * saturation
    sector = np.mod(hue, np.float32(360.0)) / np.float32(60.0)
    wave = np.abs(np.mod(sector, np.float32(2.0)) - np.float32(1.0))
    secondary = chroma * (np.float32(1.0) - wave)
    offset = lightness - chroma * np.float32(0.5)

    zero = np.zeros_like(chroma)
    red = np.select(
        [sector < 1.0, sector < 2.0, sector < 3.0, sector < 4.0, sector < 5.0],
        [chroma, secondary, zero, zero, secondary],
        default=chroma,
    )
    green = np.select(
        [sector < 1.0, sector < 2.0, sector < 3.0, sector < 4.0, sector < 5.0],
        [secondary, chroma, chroma, secondary, zero],
        default=zero,
    )
    blue = np.select(
        [sector < 1.0, sector < 2.0, sector < 3.0, sector < 4.0, sector < 5.0],
        [zero, zero, secondary, chroma, chroma],
        default=secondary,
    )
    rgb = np.stack([red, green, blue], axis=-1) + offset[..., None]
    return np.ascontiguousarray(np.clip(rgb, 0.0, 1.0), dtype=np.float32)


def _band_mix(
    hue: NDArray[np.float32],
) -> tuple[NDArray[np.intp], NDArray[np.intp], NDArray[np.float32]]:
    centers = np.asarray(HSL_BAND_HUES, dtype=np.float32)
    start = np.searchsorted(centers, hue, side="right") - 1
    start = np.clip(start, 0, len(centers) - 1)
    end = (start + 1) % len(centers)
    start_center = centers[start]
    end_center = np.where(end == 0, np.float32(360.0), centers[end])
    gap = end_center - start_center
    t = np.clip((hue - start_center) / gap, 0.0, 1.0)
    weight = t * t * (np.float32(3.0) - np.float32(2.0) * t)
    return start, end, weight.astype(np.float32, copy=False)


def _mix(
    params: NDArray[np.float32],
    start: NDArray[np.intp],
    end: NDArray[np.intp],
    weight: NDArray[np.float32],
) -> NDArray[np.float32]:
    return np.asarray(
        params[start] * (np.float32(1.0) - weight) + params[end] * weight,
        dtype=np.float32,
    )


def _limit_hue_shifts(hue_params: NDArray[np.float32]) -> NDArray[np.float32]:
    """Cap how far one band may pull past its neighbour so the hue axis stays monotone.

    A smoothstep blend over a gap peaks at a slope of 1.5 / gap, so a shift difference
    above gap * (1 - min_slope) / 1.5 folds the axis (reversed hue order, contour bands).
    The excess is split over the pair instead, which leaves distant bands untouched.
    """
    shifts = np.asarray(hue_params, dtype=np.float64).copy()
    centers = np.asarray(HSL_BAND_HUES, dtype=np.float64)
    count = shifts.shape[0]

    for _ in range(HSL_HUE_LIMIT_SWEEPS):
        settled = True
        for index in range(count):
            other = (index + 1) % count
            gap = float((centers[other] - centers[index]) % 360.0)
            limit = gap * (1.0 - HSL_HUE_MIN_SLOPE) / 1.5
            difference = shifts[index] - shifts[other]
            if abs(difference) <= limit:
                continue
            correction = (abs(difference) - limit) / 2.0
            direction = 1.0 if difference > 0.0 else -1.0
            shifts[index] -= direction * correction
            shifts[other] += direction * correction
            settled = False
        if settled:
            break

    return shifts.astype(np.float32, copy=False)


def _hue_lut(hue_params: NDArray[np.float32]) -> NDArray[np.float32]:
    """Monotone band shift sampled on a fixed 0.25 degree grid."""
    samples = np.arange(0.0, 360.0, float(HSL_HUE_LUT_STEP), dtype=np.float32)
    start, end, weight = _band_mix(samples)
    return _mix(_limit_hue_shifts(hue_params), start, end, weight)


def _sample_shift(
    lut: NDArray[np.float32],
    hue: NDArray[np.float32],
) -> NDArray[np.float32]:
    position = np.mod(hue, np.float32(360.0)) / np.float32(HSL_HUE_LUT_STEP)
    lower = np.floor(position).astype(np.intp)
    fraction = (position - lower).astype(np.float32)
    upper = (lower + 1) % lut.shape[0]
    base = np.asarray(lut[lower], dtype=np.float32)
    top = np.asarray(lut[upper], dtype=np.float32)
    return (base + (top - base) * fraction).astype(np.float32, copy=False)


def _apply_chunk(
    rgb: RgbArray,
    hue_lut: NDArray[np.float32],
    saturation_params: NDArray[np.float32],
    luminance_params: NDArray[np.float32],
) -> RgbArray:
    hue, saturation, lightness = _rgb_to_hsl(rgb)
    start, end, weight = _band_mix(hue)
    chroma = np.max(rgb, axis=-1) - np.min(rgb, axis=-1)
    # Hue keeps the wide gate (undefined near zero chroma); saturation and
    # luminance use a much lower gate so they stay useful on skin, sky and
    # pale backgrounds instead of going dead below chroma 0.02.
    hue_gate = smoothstep(chroma, HSL_HUE_GATE_LOW, HSL_HUE_GATE_HIGH)
    tone_gate = smoothstep(chroma, HSL_TONE_GATE_LOW, HSL_TONE_GATE_HIGH)
    saturation_shift = _mix(saturation_params, start, end, weight) * tone_gate
    luminance_shift = _mix(luminance_params, start, end, weight) * tone_gate
    hue_shift = _sample_shift(hue_lut, hue) * hue_gate

    active = (
        (np.abs(hue_shift) > 1e-9)
        | (np.abs(saturation_shift) > 1e-9)
        | (np.abs(luminance_shift) > 1e-9)
    )
    if not np.any(active):
        return rgb

    saturation_factor = np.clip(np.float32(1.0) + saturation_shift / np.float32(100.0), 0.0, 2.0)
    luminance_factor = np.exp2(luminance_shift / np.float32(100.0) * np.float32(HSL_LUMINANCE_EV))
    adjusted = _hsl_to_rgb(
        np.mod(hue + hue_shift, np.float32(360.0)),
        np.clip(saturation * saturation_factor, 0.0, 1.0),
        np.clip(lightness * luminance_factor, 0.0, 1.0),
    )

    result = rgb + (adjusted - rgb) * active.astype(np.float32)[..., None]
    return np.clip(result, 0.0, 1.0).astype(np.float32, copy=False)


def apply_hsl(rgb: RgbArray, hsl: HslAdjustments) -> RgbArray:
    hue_params, saturation_params, luminance_params = _parameters(hsl)
    if not (np.any(hue_params) or np.any(saturation_params) or np.any(luminance_params)):
        return rgb

    if not np.isfinite(rgb).all():
        # Hue is undefined for non-finite channels, and casting NaN to an index
        # raises; clamp them to the nearest valid colour instead.
        rgb = np.nan_to_num(rgb, nan=0.0, posinf=1.0, neginf=0.0)
    hue_lut = _hue_lut(hue_params)
    flat = np.ascontiguousarray(rgb).reshape(-1, 3)
    result = np.array(flat, dtype=np.float32, copy=True)
    for start in range(0, flat.shape[0], HSL_CHUNK_PIXELS):
        end = min(start + HSL_CHUNK_PIXELS, flat.shape[0])
        result[start:end] = _apply_chunk(
            flat[start:end],
            hue_lut,
            saturation_params,
            luminance_params,
        )
    return np.ascontiguousarray(result.reshape(rgb.shape))
