from __future__ import annotations

from math import cos, radians, sin

import cv2
import numpy as np
from numpy.typing import NDArray

from app.models.recipe import Crop, RenderQuality

RgbArray = NDArray[np.float32]


def inscribed_scale(width: int, height: int, rotation_deg: float) -> float:
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    angle = radians(abs(rotation_deg))
    denominator = cos(angle) + max(width / height, height / width) * sin(angle)
    return 1.0 / denominator


def rotate_inscribed(
    rgb: RgbArray,
    rotation_deg: float,
    *,
    quality: RenderQuality = "final",
) -> RgbArray:
    if rotation_deg == 0:
        return rgb

    height, width = rgb.shape[:2]
    scale = inscribed_scale(width, height, rotation_deg)
    target_width = max(1, round(width * scale))
    target_height = max(1, round(height * scale))

    center = ((width - 1) / 2.0, (height - 1) / 2.0)
    # The canvas is already the largest inscribed rectangle; scaling the content
    # again would expose pixels beyond the source and mirror them at the border.
    matrix = cv2.getRotationMatrix2D(center, -rotation_deg, 1.0)
    matrix[0, 2] += (target_width - 1) / 2.0 - center[0]
    matrix[1, 2] += (target_height - 1) / 2.0 - center[1]

    interpolation = cv2.INTER_LINEAR if quality == "draft" else cv2.INTER_CUBIC
    warped = cv2.warpAffine(
        rgb,
        matrix,
        (target_width, target_height),
        flags=interpolation,
        borderMode=cv2.BORDER_REFLECT_101,
    )
    return np.ascontiguousarray(np.clip(warped, 0.0, 1.0))


def crop_pixels(
    rgb: RgbArray,
    crop: Crop | None,
) -> RgbArray:
    if crop is None:
        return rgb

    height, width = rgb.shape[:2]
    x0 = min(max(round(crop.x * width), 0), width - 1)
    y0 = min(max(round(crop.y * height), 0), height - 1)
    x1 = min(max(round((crop.x + crop.w) * width), x0 + 1), width)
    y1 = min(max(round((crop.y + crop.h) * height), y0 + 1), height)
    return np.ascontiguousarray(rgb[y0:y1, x0:x1])


def apply_geometry(
    rgb: RgbArray,
    *,
    rotation_deg: float,
    crop: Crop | None,
    quality: RenderQuality = "final",
) -> RgbArray:
    rotated = rotate_inscribed(rgb, rotation_deg, quality=quality)
    return crop_pixels(rotated, crop)
