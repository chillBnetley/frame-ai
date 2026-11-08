from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from app.imaging.blend import composite_layer
from app.imaging.color_ops import apply_color
from app.imaging.geometry import crop_bounds, rotation_matrix, rotation_target_size
from app.imaging.local import apply_clarity
from app.imaging.params_map import ENGINE_VERSION, LOCAL_MASK_CHUNK_PIXELS
from app.imaging.semantic_mattes import read_matte
from app.imaging.tone import (
    apply_contrast,
    apply_tone_linear,
    linear_to_srgb,
    smoothstep,
    srgb_to_linear,
)
from app.models.recipe import Crop, LocalAdjustment, UserMask

RgbArray = NDArray[np.float32]
_LOCAL_FIELDS: tuple[str, ...] = (
    "exposure_ev",
    "contrast",
    "highlights",
    "shadows",
    "whites",
    "blacks",
    "temperature",
    "tint",
    "saturation",
    "vibrance",
    "clarity",
)


def _has_adjustments(adjustment: LocalAdjustment) -> bool:
    return any(getattr(adjustment.adjustments, name) != 0 for name in _LOCAL_FIELDS)


def _shape_weights(
    mask: UserMask,
    px: NDArray[np.float32],
    py: NDArray[np.float32],
) -> NDArray[np.float32]:
    half_width = float(mask.width) / 2.0
    half_height = float(mask.height) / 2.0
    center_x = float(mask.x) + half_width
    center_y = float(mask.y) + half_height
    feather = float(mask.feather) / 100.0

    if mask.shape == "rectangle":
        dx = np.abs(px - np.float32(center_x))
        dy = np.abs(py - np.float32(center_y))
        if feather <= 0:
            weights = ((dx <= half_width) & (dy <= half_height)).astype(np.float32)
        else:
            inner_x = half_width * (1.0 - feather)
            inner_y = half_height * (1.0 - feather)
            weights = (1.0 - smoothstep(dx, inner_x, half_width)) * (
                1.0 - smoothstep(dy, inner_y, half_height)
            )
    else:
        distance = np.sqrt(
            ((px - np.float32(center_x)) / np.float32(half_width)) ** 2
            + ((py - np.float32(center_y)) / np.float32(half_height)) ** 2
        )
        if feather <= 0:
            weights = (distance <= 1.0).astype(np.float32)
        else:
            weights = 1.0 - smoothstep(distance, 1.0 - feather, 1.0)

    if mask.inverted:
        weights = 1.0 - weights
    if mask.opacity != 100:
        weights = weights * np.float32(mask.opacity / 100.0)
    return np.asarray(weights, dtype=np.float32)


MASK_CACHE_ENTRY_LIMIT_BYTES = 24 * 1024 * 1024

MaskKey = tuple[Any, ...]


@dataclass(frozen=True)
class MaskCacheStats:
    hits: int = 0
    misses: int = 0
    entries: int = 0
    bytes_used: int = 0


class MaskWeightCache:
    """Bounded LRU of computed mask weights.

    Weights are a pure function of the mask, the canvas geometry and the
    engine, so a hit is byte-identical to recomputation. Stored arrays are
    marked read-only because callers blend with them.
    """

    def __init__(self, max_bytes: int, *, entry_limit_bytes: int = MASK_CACHE_ENTRY_LIMIT_BYTES):
        self.max_bytes = max(0, max_bytes)
        self.entry_limit_bytes = entry_limit_bytes
        self._entries: OrderedDict[MaskKey, NDArray[np.float32]] = OrderedDict()
        self._bytes_used = 0
        self._hits = 0
        self._misses = 0
        self._lock = threading.Lock()

    def get(self, key: MaskKey) -> NDArray[np.float32] | None:
        with self._lock:
            weights = self._entries.get(key)
            if weights is None:
                self._misses += 1
                return None
            self._entries.move_to_end(key)
            self._hits += 1
            return weights

    def put(self, key: MaskKey, weights: NDArray[np.float32]) -> bool:
        size = int(weights.nbytes)
        if size > self.max_bytes or size > self.entry_limit_bytes:
            return False
        with self._lock:
            existing = self._entries.pop(key, None)
            if existing is not None:
                self._bytes_used -= int(existing.nbytes)
            self._entries[key] = weights
            self._bytes_used += size
            while self._bytes_used > self.max_bytes and len(self._entries) > 1:
                _, evicted = self._entries.popitem(last=False)
                self._bytes_used -= int(evicted.nbytes)
        return True

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._bytes_used = 0

    def stats(self) -> MaskCacheStats:
        with self._lock:
            return MaskCacheStats(
                hits=self._hits,
                misses=self._misses,
                entries=len(self._entries),
                bytes_used=self._bytes_used,
            )


def _cache_key(
    mask: UserMask,
    *,
    output_width: int,
    output_height: int,
    source_width: int,
    source_height: int,
    rotation_deg: float,
    crop: Crop | None,
) -> MaskKey:
    # mask.id is deliberately absent: two masks with the same shape and
    # geometry produce the same weights.
    crop_key: tuple[Any, ...] | None = (
        None if crop is None else (float(crop.x), float(crop.y), float(crop.w), float(crop.h))
    )
    return (
        ENGINE_VERSION,
        str(mask.shape),
        str(mask.source),
        str(mask.semantic_class),
        str(mask.matte_id),
        str(mask.matte_sha256),
        str(mask.model_version),
        float(mask.x),
        float(mask.y),
        float(mask.width),
        float(mask.height),
        float(mask.feather),
        float(mask.opacity),
        bool(mask.inverted),
        int(source_width),
        int(source_height),
        int(output_width),
        int(output_height),
        float(rotation_deg),
        crop_key,
    )


_mask_cache: MaskWeightCache | None = None
_semantic_mattes_dir: Path | None = None


def configure_semantic_mattes(directory: Path | None) -> None:
    """Set the process-wide matte store used by semantic mask weights."""

    global _semantic_mattes_dir
    _semantic_mattes_dir = directory


def mask_weights(
    mask: UserMask,
    *,
    output_width: int,
    output_height: int,
    source_width: int,
    source_height: int,
    rotation_deg: float,
    crop: Crop | None,
) -> NDArray[np.float32]:
    key = _cache_key(
        mask,
        output_width=output_width,
        output_height=output_height,
        source_width=source_width,
        source_height=source_height,
        rotation_deg=rotation_deg,
        crop=crop,
    )
    cache = _mask_cache
    if cache is not None:
        cached = cache.get(key)
        if cached is not None:
            return cached
    weights = _compute_mask_weights(
        mask,
        output_width=output_width,
        output_height=output_height,
        source_width=source_width,
        source_height=source_height,
        rotation_deg=rotation_deg,
        crop=crop,
    )
    weights.setflags(write=False)
    if cache is not None:
        cache.put(key, weights)
    return weights


def semantic_mask_weights(
    mask: UserMask,
    *,
    output_width: int,
    output_height: int,
    source_width: int,
    source_height: int,
    rotation_deg: float,
    crop: Crop | None,
) -> NDArray[np.float32] | None:
    """Sample a stored semantic matte in source-normalized coordinates."""

    root = _semantic_mattes_dir
    if root is None or mask.matte_id is None or mask.matte_sha256 is None:
        return None
    key = _cache_key(
        mask,
        output_width=output_width,
        output_height=output_height,
        source_width=source_width,
        source_height=source_height,
        rotation_deg=rotation_deg,
        crop=crop,
    )
    cache = _mask_cache
    if cache is not None:
        cached = cache.get(key)
        if cached is not None:
            return cached
    matte = read_matte(root, mask.matte_id, mask.matte_sha256)
    if matte is None:
        return None
    weights = _sample_semantic_weights(
        mask,
        matte,
        output_width=output_width,
        output_height=output_height,
        source_width=source_width,
        source_height=source_height,
        rotation_deg=rotation_deg,
        crop=crop,
    )
    weights.setflags(write=False)
    if cache is not None:
        cache.put(key, weights)
    return weights


def _sample_semantic_weights(
    mask: UserMask,
    matte: NDArray[np.uint8],
    *,
    output_width: int,
    output_height: int,
    source_width: int,
    source_height: int,
    rotation_deg: float,
    crop: Crop | None,
) -> NDArray[np.float32]:
    target_width, target_height = rotation_target_size(source_width, source_height, rotation_deg)
    x0, y0, x1, y1 = crop_bounds(crop, target_width, target_height)
    if x1 - x0 != output_width or y1 - y0 != output_height:
        raise ValueError("mask geometry does not match the output dimensions")

    matrix = rotation_matrix(source_width, source_height, rotation_deg, target_width, target_height)
    inverse = np.asarray(cv2.invertAffineTransform(matrix), dtype=np.float64)
    matte_height, matte_width = matte.shape
    matte_scale_x = np.float32(max(matte_width - 1, 0))
    matte_scale_y = np.float32(max(matte_height - 1, 0))

    weights = np.zeros((output_height, output_width), dtype=np.float32)
    chunk_rows = max(1, LOCAL_MASK_CHUNK_PIXELS // max(output_width, 1))
    xs = np.arange(x0, x0 + output_width, dtype=np.float64)
    for start in range(0, output_height, chunk_rows):
        end = min(start + chunk_rows, output_height)
        ys = np.arange(y0 + start, y0 + end, dtype=np.float64)
        source_x = inverse[0, 0] * xs[None, :] + inverse[0, 1] * ys[:, None] + inverse[0, 2]
        source_y = inverse[1, 0] * xs[None, :] + inverse[1, 1] * ys[:, None] + inverse[1, 2]
        px = ((source_x + 0.5) / source_width).astype(np.float32)
        py = ((source_y + 0.5) / source_height).astype(np.float32)
        sampled = cv2.remap(
            matte,
            px * matte_scale_x,
            py * matte_scale_y,
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
        weights[start:end] = sampled.astype(np.float32) / np.float32(255.0)

    if mask.inverted:
        np.subtract(np.float32(1.0), weights, out=weights)
    if mask.opacity != 100:
        weights *= np.float32(mask.opacity / 100.0)
    return weights


def configure_mask_cache(max_bytes: int) -> None:
    """Size the process-wide weight cache; 0 disables it entirely."""
    global _mask_cache
    _mask_cache = MaskWeightCache(max_bytes) if max_bytes > 0 else None


def clear_mask_cache() -> None:
    if _mask_cache is not None:
        _mask_cache.clear()


def mask_cache_stats() -> MaskCacheStats:
    if _mask_cache is None:
        return MaskCacheStats()
    return _mask_cache.stats()


def _compute_mask_weights(
    mask: UserMask,
    *,
    output_width: int,
    output_height: int,
    source_width: int,
    source_height: int,
    rotation_deg: float,
    crop: Crop | None,
) -> NDArray[np.float32]:
    target_width, target_height = rotation_target_size(source_width, source_height, rotation_deg)
    x0, y0, x1, y1 = crop_bounds(crop, target_width, target_height)
    if x1 - x0 != output_width or y1 - y0 != output_height:
        raise ValueError("mask geometry does not match the output dimensions")

    matrix = rotation_matrix(source_width, source_height, rotation_deg, target_width, target_height)
    inverse = np.asarray(cv2.invertAffineTransform(matrix), dtype=np.float64)

    weights = np.zeros((output_height, output_width), dtype=np.float32)
    chunk_rows = max(1, LOCAL_MASK_CHUNK_PIXELS // max(output_width, 1))
    xs = np.arange(x0, x0 + output_width, dtype=np.float64)
    for start in range(0, output_height, chunk_rows):
        end = min(start + chunk_rows, output_height)
        ys = np.arange(y0 + start, y0 + end, dtype=np.float64)
        source_x = inverse[0, 0] * xs[None, :] + inverse[0, 1] * ys[:, None] + inverse[0, 2]
        source_y = inverse[1, 0] * xs[None, :] + inverse[1, 1] * ys[:, None] + inverse[1, 2]
        px = ((source_x + 0.5) / source_width).astype(np.float32)
        py = ((source_y + 0.5) / source_height).astype(np.float32)
        weights[start:end] = _shape_weights(mask, px, py)

    return weights


def _render_local(rgb: RgbArray, adjustment: LocalAdjustment) -> RgbArray:
    values = adjustment.adjustments
    linear = srgb_to_linear(rgb)
    linear = apply_tone_linear(
        linear,
        exposure_ev=values.exposure_ev,
        temperature=values.temperature,
        tint=values.tint,
        highlights=values.highlights,
        shadows=values.shadows,
        whites=values.whites,
        blacks=values.blacks,
    )
    adjusted = linear_to_srgb(linear, inplace=True)
    adjusted = apply_contrast(adjusted, values.contrast)
    adjusted = apply_color(
        adjusted,
        saturation=values.saturation,
        vibrance=values.vibrance,
    )
    adjusted = apply_clarity(adjusted, values.clarity)
    return np.ascontiguousarray(adjusted)


def local_adjustment_warnings(
    local_adjustments: tuple[LocalAdjustment, ...],
    masks: tuple[UserMask, ...],
) -> tuple[str, ...]:
    """Warnings derivable from the recipe alone, without touching pixels."""
    mask_ids = {mask.id for mask in masks}
    warnings: list[str] = []
    for item in sorted(local_adjustments, key=lambda entry: (entry.order, entry.id)):
        if not item.enabled or not _has_adjustments(item):
            continue
        if item.mask_id != "full" and item.mask_id not in mask_ids:
            warnings.append(f"local_mask_missing:{item.mask_id}")
    return tuple(warnings)


def apply_local_adjustments(
    rgb: RgbArray,
    local_adjustments: tuple[LocalAdjustment, ...],
    masks: tuple[UserMask, ...],
    *,
    source_width: int,
    source_height: int,
    rotation_deg: float,
    crop: Crop | None,
) -> tuple[RgbArray, tuple[str, ...]]:
    masks_by_id = {mask.id: mask for mask in masks}
    result = rgb
    warnings = list(local_adjustment_warnings(local_adjustments, masks))

    for item in sorted(local_adjustments, key=lambda entry: (entry.order, entry.id)):
        if not item.enabled or item.opacity == 0 or not _has_adjustments(item):
            continue
        legacy_blend = item.blend_mode == "normal" and item.opacity == 100.0

        if item.mask_id == "full":
            adjusted = _render_local(result, item)
            if legacy_blend:
                result = adjusted
            else:
                result = composite_layer(
                    result,
                    adjusted,
                    float(item.opacity / 100.0),
                    item.blend_mode,
                )
            continue

        mask = masks_by_id.get(item.mask_id)
        if mask is None:
            continue

        if mask.source == "semantic":
            weights = semantic_mask_weights(
                mask,
                output_width=result.shape[1],
                output_height=result.shape[0],
                source_width=source_width,
                source_height=source_height,
                rotation_deg=rotation_deg,
                crop=crop,
            )
            if weights is None:
                warning = f"local_matte_missing:{mask.matte_id}"
                if warning not in warnings:
                    warnings.append(warning)
                continue
        else:
            weights = mask_weights(
                mask,
                output_width=result.shape[1],
                output_height=result.shape[0],
                source_width=source_width,
                source_height=source_height,
                rotation_deg=rotation_deg,
                crop=crop,
            )
        if not bool(weights.any()):
            continue

        adjusted = _render_local(result, item)
        if legacy_blend:
            # Preserve the original in-place arithmetic order: old recipes must
            # stay byte-identical to the pre-layer renderer.
            np.subtract(adjusted, result, out=adjusted)
            adjusted *= weights[..., None]
            adjusted += result
            np.clip(adjusted, 0.0, 1.0, out=adjusted)
            result = np.ascontiguousarray(adjusted)
        else:
            layer_weight = weights[..., None] * float(item.opacity / 100.0)
            result = composite_layer(result, adjusted, layer_weight, item.blend_mode)

    return result, tuple(warnings)
