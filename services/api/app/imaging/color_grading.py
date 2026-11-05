from __future__ import annotations

import colorsys

import numpy as np
from numpy.typing import NDArray

from app.imaging.params_map import (
    COLOR_GRADING_BALANCE_SHIFT,
    COLOR_GRADING_BLEND_MAX,
    COLOR_GRADING_BLEND_MIN,
    COLOR_GRADING_CHUNK_PIXELS,
    COLOR_GRADING_HIGHLIGHT_SPLIT,
    COLOR_GRADING_SHADOW_SPLIT,
    COLOR_GRADING_STRENGTH,
)
from app.imaging.tone import smoothstep
from app.models.recipe import ColorGradeZone, ColorGrading

RgbArray = NDArray[np.float32]
_REC709 = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
_ZONES = ("shadows", "midtones", "highlights")


def _direction(zone: ColorGradeZone) -> NDArray[np.float32]:
    red, green, blue = colorsys.hsv_to_rgb((zone.hue % 360.0) / 360.0, 1.0, 1.0)
    color = np.array([red, green, blue], dtype=np.float32)
    luma = np.float32(np.dot(color, _REC709))
    return np.asarray(color - luma, dtype=np.float32)


def _parameters(
    grading: ColorGrading,
) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
    zones = [getattr(grading, name) for name in _ZONES]
    directions = np.stack([_direction(zone) for zone in zones]).astype(np.float32)
    strengths = np.array(
        [zone.saturation / 100.0 * COLOR_GRADING_STRENGTH for zone in zones],
        dtype=np.float32,
    )
    return directions, strengths


def _half_width(blending: float) -> float:
    width = COLOR_GRADING_BLEND_MIN + (COLOR_GRADING_BLEND_MAX - COLOR_GRADING_BLEND_MIN) * (
        blending / 100.0
    )
    return width / 2.0


def _apply_chunk(
    rgb: RgbArray,
    directions: NDArray[np.float32],
    strengths: NDArray[np.float32],
    balance_shift: float,
    half_width: float,
) -> RgbArray:
    luma = np.asarray(np.tensordot(rgb, _REC709, axes=([-1], [0])), dtype=np.float32)
    shifted = np.clip(luma + np.float32(balance_shift), 0.0, 1.0)
    rise = smoothstep(
        shifted,
        COLOR_GRADING_SHADOW_SPLIT - half_width,
        COLOR_GRADING_SHADOW_SPLIT + half_width,
    )
    fall = smoothstep(
        shifted,
        COLOR_GRADING_HIGHLIGHT_SPLIT - half_width,
        COLOR_GRADING_HIGHLIGHT_SPLIT + half_width,
    )
    shadows = np.float32(1.0) - rise
    midtones = rise * (np.float32(1.0) - fall)
    highlights = rise * fall
    delta = (
        shadows[..., None] * (strengths[0] * directions[0])
        + midtones[..., None] * (strengths[1] * directions[1])
        + highlights[..., None] * (strengths[2] * directions[2])
    )
    # Scale the zero-luma shift until it fits instead of clipping: clipping the
    # overflowing channel alone raises black levels and adds luma.
    magnitude = np.abs(delta)
    room = np.where(delta > np.float32(0.0), np.float32(1.0) - rgb, rgb)
    limits = np.divide(
        room,
        magnitude,
        out=np.full_like(delta, np.inf),
        where=magnitude > np.float32(1e-9),
    )
    scale = np.clip(np.min(limits, axis=-1), np.float32(0.0), np.float32(1.0))
    adjusted = rgb + delta * scale[..., None]
    # The scale already places the pinned channel on the boundary; this clip only
    # removes float32 round-off (<=1.5e-8), which the old full clip did at 1e-1.
    return np.ascontiguousarray(
        np.clip(adjusted, np.float32(0.0), np.float32(1.0)), dtype=np.float32
    )


def apply_color_grading(rgb: RgbArray, grading: ColorGrading) -> RgbArray:
    if (
        grading.shadows.saturation == 0
        and grading.midtones.saturation == 0
        and grading.highlights.saturation == 0
    ):
        return rgb

    directions, strengths = _parameters(grading)
    balance_shift = grading.balance / 100.0 * COLOR_GRADING_BALANCE_SHIFT
    half_width = _half_width(grading.blending)

    flat = np.ascontiguousarray(rgb).reshape(-1, 3)
    result = np.array(flat, dtype=np.float32, copy=True)
    for start in range(0, flat.shape[0], COLOR_GRADING_CHUNK_PIXELS):
        end = min(start + COLOR_GRADING_CHUNK_PIXELS, flat.shape[0])
        result[start:end] = _apply_chunk(
            flat[start:end],
            directions,
            strengths,
            balance_shift,
            half_width,
        )
    return np.ascontiguousarray(result.reshape(rgb.shape))
