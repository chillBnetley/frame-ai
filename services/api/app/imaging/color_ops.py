from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from app.imaging.params_map import VIBRANCE_EXPONENT

RgbArray = NDArray[np.float32]
_REC709 = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def _luminance(rgb: RgbArray) -> NDArray[np.float32]:
    return np.asarray(np.tensordot(rgb, _REC709, axes=([-1], [0])), dtype=np.float32)


def apply_saturation(rgb: RgbArray, saturation: float) -> RgbArray:
    if saturation == 0:
        return rgb

    luminance = _luminance(rgb)
    factor = np.float32(1.0 + saturation / 100.0)
    adjusted = luminance[..., None] + (rgb - luminance[..., None]) * factor
    return np.ascontiguousarray(np.clip(adjusted, 0.0, 1.0))


def apply_vibrance(rgb: RgbArray, vibrance: float) -> RgbArray:
    if vibrance == 0:
        return rgb

    luminance = _luminance(rgb)
    chroma = np.max(rgb, axis=-1) - np.min(rgb, axis=-1)
    weight = np.power(np.clip(np.float32(1.0) - chroma, 0.0, 1.0), VIBRANCE_EXPONENT)
    factor = np.float32(1.0) + np.float32(vibrance / 100.0) * weight
    adjusted = luminance[..., None] + (rgb - luminance[..., None]) * factor[..., None]
    return np.ascontiguousarray(np.clip(adjusted, 0.0, 1.0))


def apply_color(rgb: RgbArray, *, saturation: float, vibrance: float) -> RgbArray:
    result = apply_saturation(rgb, saturation)
    return apply_vibrance(result, vibrance)
