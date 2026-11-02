from __future__ import annotations

import cv2
import numpy as np
from numpy.typing import NDArray

from app.imaging.params_map import (
    CONTRAST_STRENGTH,
    HIGHLIGHTS_EV,
    SHADOWS_EV,
    TONE_MASK_SIGMA_RATIO,
    WHITE_BALANCE_BLUE_GAIN,
    WHITE_BALANCE_GREEN_TINT_GAIN,
    WHITE_BALANCE_RED_GAIN,
)

RgbArray = NDArray[np.float32]
_REC709 = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def srgb_to_linear(rgb: RgbArray) -> RgbArray:
    low = rgb / np.float32(12.92)
    high = np.power((rgb + np.float32(0.055)) / np.float32(1.055), np.float32(2.4))
    return np.ascontiguousarray(np.where(rgb <= 0.04045, low, high).astype(np.float32))


def linear_to_srgb(rgb: RgbArray) -> RgbArray:
    clipped = np.clip(rgb, 0.0, 1.0)
    low = clipped * np.float32(12.92)
    high = np.float32(1.055) * np.power(clipped, np.float32(1.0 / 2.4)) - np.float32(0.055)
    return np.ascontiguousarray(np.where(clipped <= 0.0031308, low, high).astype(np.float32))


def luminance_linear(rgb: RgbArray) -> NDArray[np.float32]:
    return np.asarray(np.tensordot(rgb, _REC709, axes=([-1], [0])), dtype=np.float32)


def luminance_srgb(rgb: RgbArray) -> NDArray[np.float32]:
    return luminance_linear(rgb)


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
    before = luminance_linear(rgb_linear)
    after = luminance_linear(adjusted)
    ratio = before / np.maximum(after, np.float32(1e-8))
    return np.ascontiguousarray(adjusted * ratio[..., None])


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

    perceptual = linear_to_srgb(luminance_linear(rgb_linear))
    if mask_sigma > 0:
        perceptual = np.asarray(
            cv2.GaussianBlur(
                perceptual,
                (0, 0),
                sigmaX=mask_sigma,
                sigmaY=mask_sigma,
                borderType=cv2.BORDER_REFLECT_101,
            ),
            dtype=np.float32,
        )

    high_mask = smoothstep(perceptual, 0.5, 1.0)
    shadow_mask = np.float32(1.0) - smoothstep(perceptual, 0.0, 0.5)
    high_ev = (highlights / 100.0) * HIGHLIGHTS_EV * high_mask
    shadow_ev = (shadows / 100.0) * SHADOWS_EV * shadow_mask
    gain = np.exp2(high_ev + shadow_ev).astype(np.float32)
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
) -> RgbArray:
    height, width = rgb_linear.shape[:2]
    result = apply_exposure(rgb_linear, exposure_ev)
    result = apply_white_balance(result, temperature, tint)
    return apply_highlights_shadows(
        result,
        highlights,
        shadows,
        mask_sigma=tone_mask_sigma(width, height),
    )


def apply_contrast(rgb: RgbArray, contrast: float) -> RgbArray:
    if contrast == 0:
        return rgb

    amount = (contrast / 100.0) * CONTRAST_STRENGTH
    perceptual = luminance_srgb(rgb)
    curved = perceptual + amount * (smoothstep(perceptual, 0.0, 1.0) - perceptual)
    ratio = np.ones_like(perceptual)
    np.divide(curved, perceptual, out=ratio, where=perceptual > np.float32(1e-6))
    result = np.clip(rgb * ratio[..., None], 0.0, 1.0)
    return np.ascontiguousarray(result)
