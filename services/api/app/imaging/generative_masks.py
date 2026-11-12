from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray
from PIL import Image

from app.models.generative import (
    GenerativeMaskDefinition,
    GenerativeMaskKind,
    GenerativeMaskQuality,
    GenerativeMaskRegion,
    GenerativeMaskStroke,
)

MaskArray = NDArray[np.uint8]


def rasterize_mask(
    definition: GenerativeMaskDefinition,
    kind: GenerativeMaskKind,
    *,
    width: int,
    height: int,
    feather: float,
    inverted: bool,
    semantic: MaskArray | None = None,
) -> MaskArray:
    if width <= 0 or height <= 0:
        raise ValueError("mask dimensions must be positive")
    mask: MaskArray = np.zeros((height, width), dtype=np.uint8)
    if kind == GenerativeMaskKind.SEMANTIC:
        if semantic is None:
            raise ValueError("a semantic mask requires a matte")
        mask = np.asarray(
            cv2.resize(semantic, (width, height), interpolation=cv2.INTER_LINEAR),
            dtype=np.uint8,
        )
    elif kind == GenerativeMaskKind.BRUSH:
        if not definition.strokes:
            raise ValueError("a brush mask requires at least one stroke")
    elif kind in (GenerativeMaskKind.RECT, GenerativeMaskKind.ELLIPSE):
        if definition.region is None:
            raise ValueError("a geometric mask requires a region")
        _draw_region(mask, definition.region, kind)
    for stroke in definition.strokes:
        _apply_stroke(mask, stroke)
    if definition.expand > 0:
        radius = int(np.ceil(definition.expand))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1))
        mask = np.asarray(cv2.dilate(mask, kernel), dtype=np.uint8)
    if feather > 0:
        radius = int(np.ceil(feather))
        sigma = max(float(feather) / 3.0, 0.1)
        mask = np.asarray(
            cv2.GaussianBlur(mask, (radius * 2 + 1, radius * 2 + 1), sigma),
            dtype=np.uint8,
        )
    if inverted:
        mask = np.asarray(cv2.bitwise_not(mask), dtype=np.uint8)
    return np.ascontiguousarray(mask, dtype=np.uint8)


def mask_quality(mask: MaskArray) -> GenerativeMaskQuality:
    binary = (mask >= 128).astype(np.uint8)
    coverage = float(np.mean(mask.astype(np.float32)) / 255.0)
    count, _ = cv2.connectedComponents(binary, connectivity=8)
    component_count = max(0, count - 1)
    touches_border = bool(
        np.any(binary[0, :])
        or np.any(binary[-1, :])
        or np.any(binary[:, 0])
        or np.any(binary[:, -1])
    )
    warnings: list[str] = []
    if component_count > 16:
        warnings.append("mask_many_components")
    if touches_border:
        warnings.append("mask_touches_border")
    return GenerativeMaskQuality(
        coverage=coverage,
        component_count=component_count,
        touches_border=touches_border,
        warnings=warnings,
    )


def encode_mask(mask: MaskArray) -> bytes:
    output = BytesIO()
    Image.fromarray(mask, mode="L").save(output, format="PNG", compress_level=6)
    return output.getvalue()


def mask_sha256(mask: MaskArray) -> str:
    return hashlib.sha256(np.ascontiguousarray(mask, dtype=np.uint8).tobytes()).hexdigest()


def decode_mask(
    data: bytes,
    *,
    width: int,
    height: int,
    expected_sha256: str,
) -> MaskArray:
    try:
        with Image.open(BytesIO(data)) as opened:
            if (
                opened.format != "PNG"
                or opened.mode != "L"
                or getattr(opened, "is_animated", False)
            ):
                raise ValueError("the mask must be a static grayscale PNG")
            if opened.size != (width, height):
                raise ValueError("mask dimensions do not match the base image")
            mask = np.asarray(opened, dtype=np.uint8)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError("the mask could not be decoded") from exc
    raw = np.ascontiguousarray(mask, dtype=np.uint8)
    if mask_sha256(raw) != expected_sha256:
        raise ValueError("the mask pixel hash does not match")
    return raw


def read_mask(
    path: Path,
    *,
    width: int,
    height: int,
    expected_sha256: str,
    max_bytes: int,
) -> MaskArray:
    try:
        size = path.stat().st_size
        if size <= 0 or size > max_bytes:
            raise ValueError("the mask file size is invalid")
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError("the mask file is unavailable") from exc
    return decode_mask(
        data,
        width=width,
        height=height,
        expected_sha256=expected_sha256,
    )


def _draw_region(
    mask: MaskArray,
    region: GenerativeMaskRegion,
    kind: GenerativeMaskKind,
) -> None:
    height, width = mask.shape
    x0 = int(np.rint(region.x * max(width - 1, 0)))
    y0 = int(np.rint(region.y * max(height - 1, 0)))
    x1 = int(np.rint((region.x + region.width) * max(width - 1, 0)))
    y1 = int(np.rint((region.y + region.height) * max(height - 1, 0)))
    if kind == GenerativeMaskKind.RECT:
        cv2.rectangle(mask, (x0, y0), (x1, y1), 255, -1, lineType=cv2.LINE_AA)
        return
    center = (int(np.rint((x0 + x1) / 2)), int(np.rint((y0 + y1) / 2)))
    axes = (max(1, int(np.rint((x1 - x0) / 2))), max(1, int(np.rint((y1 - y0) / 2))))
    cv2.ellipse(mask, center, axes, 0, 0, 360, 255, -1, lineType=cv2.LINE_AA)


def _apply_stroke(mask: MaskArray, stroke: GenerativeMaskStroke) -> None:
    height, width = mask.shape
    radius = max(0.5, stroke.radius * min(width, height))
    points = [
        (point.x * max(width - 1, 0), point.y * max(height - 1, 0)) for point in stroke.points
    ]
    for index in range(len(points)):
        start = points[index]
        end = points[min(index + 1, len(points) - 1)]
        _apply_segment(mask, start, end, radius, stroke.hardness / 100.0, stroke.mode)


def _apply_segment(
    mask: MaskArray,
    start: tuple[float, float],
    end: tuple[float, float],
    radius: float,
    hardness: float,
    mode: str,
) -> None:
    height, width = mask.shape
    x0 = max(0, int(np.floor(min(start[0], end[0]) - radius)))
    y0 = max(0, int(np.floor(min(start[1], end[1]) - radius)))
    x1 = min(width, int(np.ceil(max(start[0], end[0]) + radius)) + 1)
    y1 = min(height, int(np.ceil(max(start[1], end[1]) + radius)) + 1)
    if x0 >= x1 or y0 >= y1:
        return
    xs = np.arange(x0, x1, dtype=np.float32)
    ys = np.arange(y0, y1, dtype=np.float32)
    dx = np.float32(end[0] - start[0])
    dy = np.float32(end[1] - start[1])
    length_squared = dx * dx + dy * dy
    px = xs[None, :] - np.float32(start[0])
    py = ys[:, None] - np.float32(start[1])
    if length_squared > 0:
        projection = np.clip((px * dx + py * dy) / length_squared, 0.0, 1.0)
        nearest_x = px - projection * dx
        nearest_y = py - projection * dy
    else:
        nearest_x = px
        nearest_y = py
    distance = np.sqrt(nearest_x * nearest_x + nearest_y * nearest_y)
    inner = np.float32(radius * hardness)
    outer = np.float32(radius)
    position = np.clip((distance - inner) / max(float(outer - inner), 1e-6), 0.0, 1.0)
    smooth = position * position * (3.0 - 2.0 * position)
    stamp = np.rint((1.0 - smooth) * 255.0).astype(np.uint8)
    target = mask[y0:y1, x0:x1]
    if mode == "add":
        np.maximum(target, stamp, out=target)
    else:
        np.minimum(target, 255 - stamp, out=target)


__all__ = [
    "MaskArray",
    "decode_mask",
    "encode_mask",
    "mask_quality",
    "mask_sha256",
    "rasterize_mask",
    "read_mask",
]
