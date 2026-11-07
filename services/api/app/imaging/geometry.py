from __future__ import annotations

from math import cos, radians, sin
from typing import Any, TypeAlias

import cv2
import numpy as np
from numpy.typing import NDArray

from app.models.recipe import Crop, RenderQuality

RgbArray = NDArray[np.float32]
AlphaArray = NDArray[np.float32]
Pixels: TypeAlias = NDArray[Any]
_ALPHA_EPSILON = 1e-6


def inscribed_scale(width: int, height: int, rotation_deg: float) -> float:
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    angle = radians(abs(rotation_deg))
    denominator = cos(angle) + max(width / height, height / width) * sin(angle)
    return 1.0 / denominator


def rotation_target_size(width: int, height: int, rotation_deg: float) -> tuple[int, int]:
    scale = inscribed_scale(width, height, rotation_deg)
    return max(1, round(width * scale)), max(1, round(height * scale))


def rotation_matrix(
    width: int,
    height: int,
    rotation_deg: float,
    target_width: int,
    target_height: int,
) -> NDArray[np.float64]:
    center = ((width - 1) / 2.0, (height - 1) / 2.0)
    # The canvas is already the largest inscribed rectangle; scaling the content
    # again would expose pixels beyond the source and mirror them at the border.
    matrix = cv2.getRotationMatrix2D(center, -rotation_deg, 1.0)
    matrix[0, 2] += (target_width - 1) / 2.0 - center[0]
    matrix[1, 2] += (target_height - 1) / 2.0 - center[1]
    return np.asarray(matrix, dtype=np.float64)


def crop_bounds(
    crop: Crop | None,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    if crop is None:
        return 0, 0, width, height
    x0 = min(max(round(crop.x * width), 0), width - 1)
    y0 = min(max(round(crop.y * height), 0), height - 1)
    x1 = min(max(round((crop.x + crop.w) * width), x0 + 1), width)
    y1 = min(max(round((crop.y + crop.h) * height), y0 + 1), height)
    return x0, y0, x1, y1


def _check_alpha(rgb: Pixels, alpha: Pixels) -> None:
    if alpha.shape != rgb.shape[:2]:
        raise ValueError("alpha must be an HxW array matching the RGB pixels")


def _alpha_as_unit(alpha: Pixels) -> AlphaArray:
    values = np.asarray(alpha, dtype=np.float32)
    if np.issubdtype(alpha.dtype, np.integer):
        values = values / float(np.iinfo(alpha.dtype).max)
    return np.ascontiguousarray(np.clip(values, 0.0, 1.0))


def _cast_like(values: NDArray[np.float32], reference: Pixels) -> Pixels:
    """Cast unit-range floats back to the reference's 0..max encoding."""
    if np.issubdtype(reference.dtype, np.integer):
        info = np.iinfo(reference.dtype)
        scaled = values * float(info.max)
        return np.clip(np.rint(scaled), info.min, info.max).astype(reference.dtype)
    return values.astype(reference.dtype, copy=False)


def _unpremultiply(
    premultiplied: NDArray[np.float32],
    alpha: AlphaArray,
) -> NDArray[np.float32]:
    safe = alpha > _ALPHA_EPSILON
    rgb = np.zeros_like(premultiplied)
    np.divide(premultiplied, alpha[..., None], out=rgb, where=safe[..., None])
    rgb = np.clip(rgb, 0.0, 1.0)
    rgb[~safe] = 0.0
    return np.ascontiguousarray(rgb)


def rotate_inscribed(
    rgb: RgbArray,
    rotation_deg: float,
    *,
    quality: RenderQuality = "final",
) -> RgbArray:
    if rotation_deg == 0:
        return rgb

    height, width = rgb.shape[:2]
    target_width, target_height = rotation_target_size(width, height, rotation_deg)
    matrix = rotation_matrix(width, height, rotation_deg, target_width, target_height)

    interpolation = cv2.INTER_LINEAR if quality == "draft" else cv2.INTER_CUBIC
    warped = cv2.warpAffine(
        rgb,
        matrix,
        (target_width, target_height),
        flags=interpolation,
        borderMode=cv2.BORDER_REFLECT_101,
    )
    return np.ascontiguousarray(np.clip(warped, 0.0, 1.0))


def _rotate_inscribed_alpha(
    rgb: RgbArray,
    alpha: AlphaArray,
    rotation_deg: float,
    *,
    quality: RenderQuality,
) -> tuple[RgbArray, AlphaArray]:
    if rotation_deg == 0:
        return rgb, alpha

    height, width = rgb.shape[:2]
    target_width, target_height = rotation_target_size(width, height, rotation_deg)
    matrix = rotation_matrix(width, height, rotation_deg, target_width, target_height)
    interpolation = cv2.INTER_LINEAR if quality == "draft" else cv2.INTER_CUBIC

    premultiplied = rgb * alpha[..., None]
    warped_rgb: NDArray[np.float32] = np.asarray(
        cv2.warpAffine(
            premultiplied,
            matrix,
            (target_width, target_height),
            flags=interpolation,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0.0, 0.0, 0.0),
        ),
        dtype=np.float32,
    )
    # Linear alpha keeps the coverage mask monotonic; cubic can ring past 0/1.
    warped_alpha: NDArray[np.float32] = np.asarray(
        cv2.warpAffine(
            alpha,
            matrix,
            (target_width, target_height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0.0,
        ),
        dtype=np.float32,
    )
    clipped_alpha: AlphaArray = np.ascontiguousarray(
        np.clip(warped_alpha, 0.0, 1.0).astype(np.float32)
    )
    return _unpremultiply(warped_rgb, clipped_alpha), clipped_alpha


def crop_pixels(
    rgb: RgbArray,
    crop: Crop | None,
) -> RgbArray:
    if crop is None:
        return rgb

    height, width = rgb.shape[:2]
    x0, y0, x1, y1 = crop_bounds(crop, width, height)
    return np.ascontiguousarray(rgb[y0:y1, x0:x1])


def apply_geometry(
    rgb: RgbArray,
    alpha: AlphaArray | None = None,
    *,
    rotation_deg: float,
    crop: Crop | None,
    quality: RenderQuality = "final",
) -> tuple[RgbArray, AlphaArray | None]:
    if alpha is None:
        rotated = rotate_inscribed(rgb, rotation_deg, quality=quality)
        return np.ascontiguousarray(crop_pixels(rotated, crop)), None

    _check_alpha(rgb, alpha)
    unit_alpha = _alpha_as_unit(alpha)
    rotated_rgb, rotated_alpha = _rotate_inscribed_alpha(
        rgb,
        unit_alpha,
        rotation_deg,
        quality=quality,
    )
    # A no-op rotation returns the straight colour array, so normalise it once
    # more: fully transparent pixels must be deterministic black.
    rotated_rgb = _unpremultiply(rotated_rgb * rotated_alpha[..., None], rotated_alpha)
    if crop is None:
        return rotated_rgb, rotated_alpha
    height, width = rotated_rgb.shape[:2]
    x0, y0, x1, y1 = crop_bounds(crop, width, height)
    return (
        np.ascontiguousarray(rotated_rgb[y0:y1, x0:x1]),
        np.ascontiguousarray(rotated_alpha[y0:y1, x0:x1]),
    )


def canvas_size(
    width: int,
    height: int,
    rotation_deg: float,
    crop: Crop | None,
) -> tuple[int, int]:
    """Rendered canvas after rotation and crop, matching apply_geometry exactly."""
    rotated_width, rotated_height = rotation_target_size(width, height, rotation_deg)
    x0, y0, x1, y1 = crop_bounds(crop, rotated_width, rotated_height)
    return x1 - x0, y1 - y0


def export_target_size(
    width: int,
    height: int,
    rotation_deg: float,
    crop: Crop | None,
    max_edge: int | None,
) -> tuple[int, int, float]:
    """(target width, target height, source scale) for an export request.

    Never upscales: a max edge at or above the canvas returns the full canvas.
    """
    canvas_width, canvas_height = canvas_size(width, height, rotation_deg, crop)
    longest = max(canvas_width, canvas_height)
    if max_edge is None or max_edge >= longest:
        return canvas_width, canvas_height, 1.0
    scale = max_edge / longest
    return max(1, round(canvas_width * scale)), max(1, round(canvas_height * scale)), scale


def resize_exact(pixels: Pixels, width: int, height: int) -> Pixels:
    """Scale to exactly width x height, keeping the dtype of the input array."""
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    source_height, source_width = pixels.shape[:2]
    if (source_width, source_height) == (width, height):
        return pixels
    resized = cv2.resize(pixels, (width, height), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(resized)


def resize_exact_alpha(
    pixels: Pixels,
    alpha: Pixels,
    width: int,
    height: int,
) -> tuple[Pixels, Pixels]:
    """Alpha-aware ``resize_exact``: premultiplied, INTER_AREA, dtype preserved."""
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    _check_alpha(pixels, alpha)
    source_height, source_width = pixels.shape[:2]
    if (source_width, source_height) == (width, height):
        return pixels, alpha

    unit_alpha = _alpha_as_unit(alpha)
    if np.issubdtype(pixels.dtype, np.integer):
        unit_rgb = pixels.astype(np.float32) / float(np.iinfo(pixels.dtype).max)
    else:
        unit_rgb = pixels.astype(np.float32)
    premultiplied = unit_rgb * unit_alpha[..., None]
    resized_rgb: NDArray[np.float32] = np.asarray(
        cv2.resize(
            premultiplied,
            (width, height),
            interpolation=cv2.INTER_AREA,
        ),
        dtype=np.float32,
    )
    resized_alpha: AlphaArray = np.ascontiguousarray(
        np.clip(
            cv2.resize(unit_alpha, (width, height), interpolation=cv2.INTER_AREA),
            0.0,
            1.0,
        ).astype(np.float32)
    )
    unpremultiplied = _unpremultiply(resized_rgb, resized_alpha)
    return (
        np.ascontiguousarray(_cast_like(unpremultiplied, pixels)),
        np.ascontiguousarray(_cast_like(resized_alpha, alpha)),
    )
