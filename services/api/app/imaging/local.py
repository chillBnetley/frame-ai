from __future__ import annotations

import cv2
import numpy as np
from numpy.typing import NDArray

from app.imaging.params_map import (
    CLARITY_MAX_SIGMA,
    CLARITY_MIN_SIGMA,
    CLARITY_SIGMA_RATIO,
    CLARITY_STRENGTH,
    VIGNETTE_NEGATIVE_EV,
    VIGNETTE_POSITIVE_EV,
)
from app.imaging.tone import (
    linear_to_srgb,
    luma_srgb,
    smoothstep,
    srgb_to_linear,
)

RgbArray = NDArray[np.float32]
_EPSILON = np.float32(1e-6)
_VIGNETTE_INNER = 0.4
_VIGNETTE_OUTER = 1.0


def _blur(channel: NDArray[np.float32], sigma: float) -> NDArray[np.float32]:
    return np.asarray(
        cv2.GaussianBlur(
            channel,
            (0, 0),
            sigmaX=sigma,
            sigmaY=sigma,
            borderType=cv2.BORDER_REFLECT_101,
        ),
        dtype=np.float32,
    )


def _detail_sigma(ratio: float, minimum: float, maximum: float, width: int, height: int) -> float:
    return min(max(ratio * max(width, height), minimum), maximum)


def apply_clarity(rgb: RgbArray, clarity: float) -> RgbArray:
    if clarity == 0:
        return rgb

    height, width = rgb.shape[:2]
    sigma = _detail_sigma(
        CLARITY_SIGMA_RATIO,
        CLARITY_MIN_SIGMA,
        CLARITY_MAX_SIGMA,
        width,
        height,
    )
    luminance = luma_srgb(rgb)
    detail = luminance - _blur(luminance, sigma)
    midtone = np.clip(np.float32(4.0) * luminance * (np.float32(1.0) - luminance), 0.0, 1.0)
    delta = detail * midtone * np.float32(CLARITY_STRENGTH * clarity / 100.0)

    adjusted = luminance + delta
    ratio = np.ones_like(luminance)
    np.divide(adjusted, luminance, out=ratio, where=luminance > _EPSILON)
    return np.ascontiguousarray(np.clip(rgb * ratio[..., None], 0.0, 1.0))


def vignette_falloff(width: int, height: int) -> NDArray[np.float32]:
    x = (np.arange(width, dtype=np.float32) - (width - 1) / 2.0) / max((width - 1) / 2.0, 1.0)
    y = (np.arange(height, dtype=np.float32) - (height - 1) / 2.0) / max((height - 1) / 2.0, 1.0)
    distance = np.asarray(
        np.sqrt(x[None, :] ** 2 + y[:, None] ** 2) / np.float32(np.sqrt(2.0)),
        dtype=np.float32,
    )
    return smoothstep(distance, _VIGNETTE_INNER, _VIGNETTE_OUTER)


def apply_vignette(rgb: RgbArray, vignette: float) -> RgbArray:
    if vignette == 0:
        return rgb

    height, width = rgb.shape[:2]
    falloff = vignette_falloff(width, height)
    if vignette > 0:
        exposure = -VIGNETTE_POSITIVE_EV * vignette / 100.0
    else:
        exposure = VIGNETTE_NEGATIVE_EV * (-vignette) / 100.0

    linear = srgb_to_linear(rgb)
    gain = np.exp2(falloff * np.float32(exposure)).astype(np.float32)
    adjusted = linear * gain[..., None]
    return np.ascontiguousarray(np.clip(linear_to_srgb(adjusted), 0.0, 1.0))


def apply_local(rgb: RgbArray, *, clarity: float, vignette: float) -> RgbArray:
    result = apply_clarity(rgb, clarity)
    return apply_vignette(result, vignette)
