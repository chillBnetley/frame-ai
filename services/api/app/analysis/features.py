from __future__ import annotations

from math import sqrt
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from app.ai.contracts import MeasurementSummary
from app.imaging.analyzer import (
    _brightness_centroid,
    _cast_estimate,
    _edge_density_grid,
    _edges,
    _histogram32,
    _horizon_tilt,
    _noise_estimate,
    _round3,
    _saturation,
    _sharpness,
)
from app.imaging.loader import LoadedImage
from app.imaging.tone import luma_srgb, srgb_to_linear

# Reuses the phase-2 analyzer primitives so both features stay numerically aligned.
FEATURE_SET_VERSION = "frame-features/2"
HIGHLIGHT_CLIP_LEVEL = 250.0 / 255.0
SHADOW_CLIP_LEVEL = 5.0 / 255.0
DOMINANT_COLOR_LIMIT = 5
DOMINANT_QUANT_STEP = 32
DOMINANT_MERGE_DISTANCE = 48.0
COLOR_RICHNESS_SCALE = 0.5
RGB_HISTOGRAM_BINS = 32
HSV_HUE_BINS = 16
HSV_SATURATION_BINS = 8
HSV_VALUE_BINS = 8


def extract_features(
    image: LoadedImage,
    *,
    display_width: int | None = None,
    display_height: int | None = None,
) -> MeasurementSummary:
    rgb = np.clip(image.rgb, 0.0, 1.0)
    height, width = rgb.shape[:2]
    reported_width = width if display_width is None else display_width
    reported_height = height if display_height is None else display_height

    luminance = luma_srgb(rgb)
    percentiles = np.percentile(luminance, [1.0, 5.0, 50.0, 95.0, 99.0])
    p1, p5, p50, p95, p99 = (float(value) for value in percentiles)
    saturation = _saturation(rgb)
    edges = _edges(luminance)
    centroid = _brightness_centroid(luminance)
    cast = _cast_estimate(rgb)
    linear_mean = srgb_to_linear(rgb).reshape(-1, 3).mean(axis=0)
    saturation_p10, saturation_p50, saturation_p90 = (
        float(value) for value in np.percentile(saturation, [10.0, 50.0, 90.0])
    )
    dominant_colors, color_concentration = _dominant_color_stats(rgb)

    return MeasurementSummary(
        feature_set_version=FEATURE_SET_VERSION,
        width=reported_width,
        height=reported_height,
        aspect_ratio=_round3(reported_width / reported_height),
        luminance_mean=_round3(float(luminance.mean())),
        luminance_std=_round3(float(luminance.std())),
        luminance_p1=_round3(p1),
        luminance_p5=_round3(p5),
        luminance_p50=_round3(p50),
        luminance_p95=_round3(p95),
        luminance_p99=_round3(p99),
        histogram32=tuple(_histogram32(luminance)),
        highlights_pct=_round3(float(np.mean(luminance >= HIGHLIGHT_CLIP_LEVEL)) * 100.0),
        shadows_pct=_round3(float(np.mean(luminance <= SHADOW_CLIP_LEVEL)) * 100.0),
        mean_rgb_linear=tuple(_round3(float(value)) for value in linear_mean),
        cast_temperature=cast.temperature,
        cast_tint=cast.tint,
        saturation_mean=_round3(float(saturation.mean())),
        saturation_p95=_round3(float(np.percentile(saturation, 95.0))),
        saturation_p10=_round3(saturation_p10),
        saturation_p50=_round3(saturation_p50),
        saturation_p90=_round3(saturation_p90),
        color_richness=_round3(_color_richness(rgb)),
        color_concentration=_round3(color_concentration),
        sharpness=_sharpness(luminance),
        noise_estimate=_noise_estimate(luminance),
        gradient_anisotropy=_round3(_gradient_anisotropy(luminance)),
        horizon_tilt_deg=_horizon_tilt(edges),
        brightness_centroid_x=_round3(centroid[0]),
        brightness_centroid_y=_round3(centroid[1]),
        edge_density_grid_3x3=tuple(_edge_density_grid(edges)),
        dominant_colors=dominant_colors,
        rgb_histogram=_rgb_histogram(rgb),
        hsv_histogram=_hsv_histogram(rgb),
    )


def _color_richness(rgb: NDArray[np.float32]) -> float:
    red, green, blue = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    red_green = red - green
    yellow_blue = 0.5 * (red + green) - blue
    spread = sqrt(float(np.var(red_green)) + float(np.var(yellow_blue)))
    offset = sqrt(float(np.mean(red_green)) ** 2 + float(np.mean(yellow_blue)) ** 2)
    value = spread + 0.3 * offset
    return min(max(value / COLOR_RICHNESS_SCALE, 0.0), 1.0)


def _dominant_color_stats(
    rgb: NDArray[np.float32],
) -> tuple[tuple[str, ...], float]:
    pixels = np.clip(np.rint(rgb * 255.0), 0.0, 255.0).astype(np.uint8)
    quantized = np.clip(
        np.rint(pixels.astype(np.float32) / DOMINANT_QUANT_STEP) * DOMINANT_QUANT_STEP,
        0.0,
        255.0,
    ).astype(np.uint8)
    codes, counts = np.unique(quantized.reshape(-1, 3), axis=0, return_counts=True)
    order = np.lexsort((codes[:, 2], codes[:, 1], codes[:, 0], -counts))

    selected: list[NDArray[np.int32]] = []
    selected_indices: list[int] = []
    threshold = DOMINANT_MERGE_DISTANCE**2
    for index in order:
        color = codes[index].astype(np.int32)
        if any(float(np.sum((color - kept) ** 2)) < threshold for kept in selected):
            continue
        selected.append(color)
        selected_indices.append(int(index))
        if len(selected) == DOMINANT_COLOR_LIMIT:
            break

    total = int(counts.sum())
    covered = sum(int(counts[index]) for index in selected_indices)
    concentration = 0.0 if total <= 0 else min(max(covered / total, 0.0), 1.0)
    colors = tuple(f"#{red:02X}{green:02X}{blue:02X}" for red, green, blue in selected)
    return colors, concentration


def _rgb_histogram(rgb: NDArray[np.float32]) -> tuple[tuple[float, ...], ...]:
    return tuple(
        _normalized_histogram(
            rgb[..., channel].reshape(-1),
            bins=RGB_HISTOGRAM_BINS,
            value_range=(0.0, 1.0),
        )
        for channel in range(3)
    )


def _hsv_histogram(rgb: NDArray[np.float32]) -> tuple[tuple[float, ...], ...]:
    hsv = cv2.cvtColor(rgb.astype(np.float32), cv2.COLOR_RGB2HSV)
    return (
        _normalized_histogram(hsv[..., 0].reshape(-1), bins=HSV_HUE_BINS, value_range=(0.0, 360.0)),
        _normalized_histogram(
            hsv[..., 1].reshape(-1),
            bins=HSV_SATURATION_BINS,
            value_range=(0.0, 1.0),
        ),
        _normalized_histogram(
            hsv[..., 2].reshape(-1),
            bins=HSV_VALUE_BINS,
            value_range=(0.0, 1.0),
        ),
    )


def _normalized_histogram(
    values: NDArray[Any],
    *,
    bins: int,
    value_range: tuple[float, float],
) -> tuple[float, ...]:
    counts, _ = np.histogram(values, bins=bins, range=value_range)
    total = float(counts.sum())
    if total <= 0.0:
        return (0.0,) * bins
    rounded = [round(float(count) / total, 6) for count in counts]
    rounded[-1] = round(1.0 - sum(rounded[:-1]), 6)
    return tuple(min(max(value, 0.0), 1.0) for value in rounded)


def _gradient_anisotropy(luminance: NDArray[np.float32]) -> float:
    gradient_x = cv2.Sobel(luminance, cv2.CV_32F, 1, 0, ksize=3)
    gradient_y = cv2.Sobel(luminance, cv2.CV_32F, 0, 1, ksize=3)
    variance_x = float(np.var(gradient_x))
    variance_y = float(np.var(gradient_y))
    total = variance_x + variance_y
    if total <= 1e-12:
        return 0.0
    return min(max(abs(variance_x - variance_y) / total, 0.0), 1.0)


__all__ = [
    "FEATURE_SET_VERSION",
    "extract_features",
]
