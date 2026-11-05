from __future__ import annotations

import cv2
import numpy as np
from numpy.typing import NDArray

from app.imaging.params_map import (
    BLACKS_EV,
    BLACKS_MASK_END,
    CONTRAST_CHROMA_TOLERANCE,
    CONTRAST_STRENGTH,
    HIGHLIGHTS_EV,
    SHADOWS_EV,
    TONE_MASK_SIGMA_RATIO,
    WHITE_BALANCE_BLUE_GAIN,
    WHITE_BALANCE_GREEN_TINT_GAIN,
    WHITE_BALANCE_RED_GAIN,
    WHITES_EV,
    WHITES_MASK_START,
)

RgbArray = NDArray[np.float32]
_REC709 = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def srgb_to_linear(rgb: RgbArray) -> RgbArray:
    out = np.empty_like(rgb)
    high = np.empty_like(rgb)
    np.add(rgb, np.float32(0.055), out=high)
    np.divide(high, np.float32(1.055), out=high)
    np.power(high, np.float32(2.4), out=high)
    np.divide(rgb, np.float32(12.92), out=out)
    np.copyto(out, high, where=rgb > np.float32(0.04045))
    return out


def linear_to_srgb(rgb: RgbArray, *, inplace: bool = False) -> RgbArray:
    if inplace:
        clipped = rgb
        np.clip(clipped, 0.0, 1.0, out=clipped)
    else:
        clipped = np.clip(rgb, 0.0, 1.0)
    high_mask = clipped > np.float32(0.0031308)
    high = np.empty_like(clipped)
    np.power(clipped, np.float32(1.0 / 2.4), out=high)
    np.multiply(high, np.float32(1.055), out=high)
    high -= np.float32(0.055)
    out = clipped if inplace else np.empty_like(clipped)
    np.multiply(clipped, np.float32(12.92), out=out)
    np.copyto(out, high, where=high_mask)
    return out


def luminance_linear(rgb: RgbArray) -> NDArray[np.float32]:
    return np.asarray(np.tensordot(rgb, _REC709, axes=([-1], [0])), dtype=np.float32)


def luma_srgb(rgb: RgbArray) -> NDArray[np.float32]:
    """Rec.709 luma (Y') of sRGB-encoded values.

    This is the weighted sum of gamma-encoded channels, not a luminance
    conversion.  Linear data must go through ``luminance_linear`` and be
    encoded explicitly with ``linear_to_srgb`` when a gamma-domain value is
    needed; using this on linear data silently brightens every adjustment.
    """
    return np.asarray(np.tensordot(rgb, _REC709, axes=([-1], [0])), dtype=np.float32)


def smoothstep(x: NDArray[np.float32], edge0: float, edge1: float) -> NDArray[np.float32]:
    if edge1 <= edge0:
        raise ValueError("edge1 must be greater than edge0")
    t = np.clip((x - np.float32(edge0)) / np.float32(edge1 - edge0), 0.0, 1.0)
    return np.asarray(t * t * (np.float32(3.0) - np.float32(2.0) * t), dtype=np.float32)


def apply_exposure(rgb_linear: RgbArray, exposure_ev: float) -> RgbArray:
    if exposure_ev == 0:
        return rgb_linear
    gain = np.float32(2.0**exposure_ev)
    return np.ascontiguousarray(rgb_linear * gain)


def _mean_luminance(rgb_linear: RgbArray) -> float:
    return float(np.mean(rgb_linear, axis=(0, 1), dtype=np.float64) @ _REC709.astype(np.float64))


def apply_white_balance(
    rgb_linear: RgbArray,
    temperature: float,
    tint: float,
) -> RgbArray:
    if temperature == 0 and tint == 0:
        return rgb_linear

    warmth = temperature / 100.0
    magenta = tint / 100.0
    gains = np.array(
        [
            1.0 + WHITE_BALANCE_RED_GAIN * warmth,
            1.0 - WHITE_BALANCE_GREEN_TINT_GAIN * magenta,
            1.0 - WHITE_BALANCE_BLUE_GAIN * warmth,
        ],
        dtype=np.float32,
    )
    adjusted = rgb_linear * gains
    before = _mean_luminance(rgb_linear)
    after = _mean_luminance(adjusted)
    if before <= 0.0 or after <= 0.0:
        return np.ascontiguousarray(adjusted)
    # One scalar for the whole image: a per-pixel ratio would cancel the gain on any
    # fully saturated pixel, so pure red/blue never moved at all.
    return np.ascontiguousarray(adjusted * np.float32(before / after))


def _mask_luminance(rgb_linear: RgbArray, mask_sigma: float) -> NDArray[np.float32]:
    perceptual = linear_to_srgb(luminance_linear(rgb_linear))
    if mask_sigma == 0:
        return perceptual
    return np.asarray(
        cv2.GaussianBlur(
            perceptual,
            (0, 0),
            sigmaX=mask_sigma,
            sigmaY=mask_sigma,
            borderType=cv2.BORDER_REFLECT_101,
        ),
        dtype=np.float32,
    )


def apply_highlights_shadows(
    rgb_linear: RgbArray,
    highlights: float,
    shadows: float,
    *,
    mask_sigma: float,
) -> RgbArray:
    if highlights == 0 and shadows == 0:
        return rgb_linear
    if mask_sigma < 0:
        raise ValueError("mask_sigma must not be negative")

    perceptual = _mask_luminance(rgb_linear, mask_sigma)
    high_mask = smoothstep(perceptual, 0.5, 1.0)
    shadow_mask = np.float32(1.0) - smoothstep(perceptual, 0.0, 0.5)
    high_ev = (highlights / 100.0) * HIGHLIGHTS_EV * high_mask
    shadow_ev = (shadows / 100.0) * SHADOWS_EV * shadow_mask
    gain = np.exp2(high_ev + shadow_ev).astype(np.float32)
    return np.ascontiguousarray(rgb_linear * gain[..., None])


def apply_whites_blacks(
    rgb_linear: RgbArray,
    whites: float,
    blacks: float,
    *,
    mask_sigma: float,
) -> RgbArray:
    if whites == 0 and blacks == 0:
        return rgb_linear
    if mask_sigma < 0:
        raise ValueError("mask_sigma must not be negative")

    perceptual = _mask_luminance(rgb_linear, mask_sigma)
    white_mask = smoothstep(perceptual, WHITES_MASK_START, 1.0)
    black_mask = np.float32(1.0) - smoothstep(perceptual, 0.0, BLACKS_MASK_END)
    white_ev = (whites / 100.0) * WHITES_EV * white_mask
    # BLACKS_EV is negative: positive Blacks darkens, matching Lightroom/ACR.
    black_ev = (blacks / 100.0) * BLACKS_EV * black_mask
    gain = np.exp2(white_ev + black_ev).astype(np.float32)
    return np.ascontiguousarray(rgb_linear * gain[..., None])


def tone_mask_sigma(width: int, height: int) -> float:
    return TONE_MASK_SIGMA_RATIO * max(width, height)


def apply_tone_linear(
    rgb_linear: RgbArray,
    *,
    exposure_ev: float,
    temperature: float,
    tint: float,
    highlights: float,
    shadows: float,
    whites: float = 0.0,
    blacks: float = 0.0,
) -> RgbArray:
    height, width = rgb_linear.shape[:2]
    sigma = tone_mask_sigma(width, height)
    result = apply_exposure(rgb_linear, exposure_ev)
    result = apply_white_balance(result, temperature, tint)
    result = apply_highlights_shadows(result, highlights, shadows, mask_sigma=sigma)
    return apply_whites_blacks(result, whites, blacks, mask_sigma=sigma)


def apply_contrast(rgb: RgbArray, contrast: float) -> RgbArray:
    if contrast == 0:
        return rgb

    amount = (contrast / 100.0) * CONTRAST_STRENGTH
    perceptual = luma_srgb(rgb)
    curved = perceptual + amount * (smoothstep(perceptual, 0.0, 1.0) - perceptual)
    ratio = np.ones_like(perceptual)
    np.divide(curved, perceptual, out=ratio, where=perceptual > np.float32(1e-6))
    # Multiplying all channels by the luma ratio also multiplied chroma by it, so
    # strong contrast shifted saturation by ~14% on coloured pixels.  Keep the
    # curve's luma and scale the chroma vector back into a +/-5% band around its
    # original value; the Rec.709 weights sum to one, so scaling chroma around
    # ``curved`` preserves that luma exactly before gamut clipping.
    chroma_scale = np.clip(
        ratio,
        np.float32(1.0 - CONTRAST_CHROMA_TOLERANCE),
        np.float32(1.0 + CONTRAST_CHROMA_TOLERANCE),
    )
    result = curved[..., None] + (rgb - perceptual[..., None]) * chroma_scale[..., None]
    return np.ascontiguousarray(np.clip(result, 0.0, 1.0))
