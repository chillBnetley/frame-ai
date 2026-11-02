from __future__ import annotations

from math import atan2, degrees, hypot, log1p, pi, sqrt

import cv2
import numpy as np
from numpy.typing import NDArray

from app.imaging.loader import LoadedImage, resize_to_max_edge
from app.imaging.tone import luminance_srgb, srgb_to_linear
from app.models.analysis import (
    AnalysisFeatures,
    CastEstimate,
    ClippingFeatures,
    ColorFeatures,
    CompositionFeatures,
    DetailFeatures,
    LuminanceFeatures,
    SceneHints,
    SizeFeatures,
)

ANALYZER_VERSION = "frame-analyzer/1"
ANALYZER_MAX_EDGE = 1024
HISTOGRAM_BINS = 32
HISTOGRAM_STEPS = 1000

CAST_SCALE = 200.0
SATURATION_EPSILON = 1e-6

SHARPNESS_VARIANCE_SCALE = 1000.0
NOISE_SIGMA_SCALE = 0.05

CANNY_LOW = 50
CANNY_HIGH = 150
HORIZON_MAX_ANGLE = 15.0
HORIZON_HOUGH_THRESHOLD = 50
HORIZON_MIN_LENGTH_RATIO = 0.15
HORIZON_TOP_LINES = 20
HORIZON_MIN_LINES = 3
HORIZON_INLIER_DEG = 3.0

LOW_LIGHT_P50 = 0.2
HIGH_KEY_P50 = 0.7
LOW_KEY_P95 = 0.6
MONOCHROME_SATURATION = 0.03


def _round3(value: float) -> float:
    return round(float(value), 3) + 0.0


def _clamp100(value: float) -> float:
    return min(max(value, -100.0), 100.0)


def _histogram32(luminance: NDArray[np.float32]) -> list[float]:
    counts, _ = np.histogram(luminance, bins=HISTOGRAM_BINS, range=(0.0, 1.0))
    scaled = counts.astype(np.float64) * HISTOGRAM_STEPS / max(int(counts.sum()), 1)
    floors = np.floor(scaled).astype(np.int64)
    remainder = HISTOGRAM_STEPS - int(floors.sum())
    if remainder > 0:
        order = np.argsort(-(scaled - floors), kind="stable")
        floors[order[:remainder]] += 1
    return [int(value) / HISTOGRAM_STEPS for value in floors]


def _saturation(rgb: NDArray[np.float32]) -> NDArray[np.float32]:
    maximum = np.max(rgb, axis=-1)
    minimum = np.min(rgb, axis=-1)
    result = np.zeros_like(maximum)
    np.divide(maximum - minimum, maximum, out=result, where=maximum > SATURATION_EPSILON)
    return np.asarray(result, dtype=np.float32)


def _cast_estimate(rgb: NDArray[np.float32]) -> CastEstimate:
    means = srgb_to_linear(rgb).reshape(-1, 3).mean(axis=0)
    red, green, blue = (float(value) for value in means)
    total = red + green + blue
    if total <= SATURATION_EPSILON:
        return CastEstimate(temperature=0.0, tint=0.0)
    temperature = _clamp100(CAST_SCALE * (red - blue) / total)
    tint = _clamp100(-CAST_SCALE * (green - (red + blue) / 2.0) / total)
    return CastEstimate(temperature=_round3(temperature), tint=_round3(tint))


def _sharpness(luminance: NDArray[np.float32]) -> float:
    laplacian = cv2.Laplacian(luminance, cv2.CV_32F)
    variance = float(np.var(laplacian))
    normalized = log1p(variance * SHARPNESS_VARIANCE_SCALE) / log1p(SHARPNESS_VARIANCE_SCALE)
    return _round3(min(max(normalized, 0.0), 1.0))


def _noise_estimate(luminance: NDArray[np.float32]) -> float:
    kernel = np.array(
        [[1.0, -2.0, 1.0], [-2.0, 4.0, -2.0], [1.0, -2.0, 1.0]],
        dtype=np.float32,
    )
    response = cv2.filter2D(luminance, cv2.CV_32F, kernel, borderType=cv2.BORDER_REFLECT_101)
    sigma = float(np.mean(np.abs(response))) * sqrt(pi / 2.0) / 6.0
    return _round3(min(max(sigma / NOISE_SIGMA_SCALE, 0.0), 1.0))


def _edges(luminance: NDArray[np.float32]) -> NDArray[np.uint8]:
    quantized = np.clip(np.rint(luminance * 255.0), 0.0, 255.0).astype(np.uint8)
    edges: NDArray[np.uint8] = np.asarray(
        cv2.Canny(quantized, CANNY_LOW, CANNY_HIGH), dtype=np.uint8
    )
    return edges


def _edge_density_grid(edges: NDArray[np.uint8]) -> list[float]:
    height, width = edges.shape[:2]
    density: list[float] = []
    for rows in np.array_split(np.arange(height), 3):
        for columns in np.array_split(np.arange(width), 3):
            block = edges[np.ix_(rows, columns)]
            density.append(_round3(float(block.mean()) / 255.0) if block.size else 0.0)
    return density


def _horizon_tilt(edges: NDArray[np.uint8]) -> float | None:
    height, width = edges.shape[:2]
    min_length = max(10, int(min(width, height) * HORIZON_MIN_LENGTH_RATIO))
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180.0,
        threshold=HORIZON_HOUGH_THRESHOLD,
        minLineLength=min_length,
        maxLineGap=max(2, int(min(width, height) * 0.02)),
    )
    if lines is None:
        return None

    candidates: list[tuple[float, float]] = []
    for line in np.asarray(lines).reshape(-1, 4):
        x1, y1, x2, y2 = (int(value) for value in line)
        length = hypot(x2 - x1, y2 - y1)
        if length < min_length:
            continue
        angle = degrees(atan2(float(y2 - y1), float(x2 - x1)))
        if angle > 90.0:
            angle -= 180.0
        if angle <= -90.0:
            angle += 180.0
        if abs(angle) <= HORIZON_MAX_ANGLE:
            candidates.append((length, angle))

    if len(candidates) < HORIZON_MIN_LINES:
        return None

    strongest = sorted(candidates, key=lambda item: item[0], reverse=True)[:HORIZON_TOP_LINES]
    median = float(np.median([angle for _, angle in strongest]))
    inliers = [angle for _, angle in strongest if abs(angle - median) <= HORIZON_INLIER_DEG]
    if len(inliers) < HORIZON_MIN_LINES:
        return None
    return _round3(float(np.median(inliers)))


def _brightness_centroid(luminance: NDArray[np.float32]) -> list[float]:
    height, width = luminance.shape[:2]
    weights = luminance.astype(np.float64)
    total = float(weights.sum())
    if total <= SATURATION_EPSILON:
        return [0.5, 0.5]

    x_centers = (np.arange(width, dtype=np.float64) + 0.5) / width
    y_centers = (np.arange(height, dtype=np.float64) + 0.5) / height
    centroid_x = float((weights.sum(axis=0) * x_centers).sum() / total)
    centroid_y = float((weights.sum(axis=1) * y_centers).sum() / total)
    return [_round3(centroid_x), _round3(centroid_y)]


def analyze(
    image: LoadedImage,
    *,
    display_width: int | None = None,
    display_height: int | None = None,
    exif_orientation: int = 1,
) -> AnalysisFeatures:
    proxy = image
    if max(image.width, image.height) > ANALYZER_MAX_EDGE:
        proxy = resize_to_max_edge(image, ANALYZER_MAX_EDGE)
    rgb = proxy.rgb
    height, width = rgb.shape[:2]

    luminance = luminance_srgb(rgb)
    percentiles = np.percentile(luminance, [1.0, 5.0, 50.0, 95.0, 99.0])
    p1, p5, p50, p95, p99 = (float(value) for value in percentiles)
    saturation = _saturation(rgb)
    saturation_mean = float(saturation.mean())
    edges = _edges(luminance)

    reported_width = width if display_width is None else display_width
    reported_height = height if display_height is None else display_height
    aspect_ratio = reported_width / reported_height if reported_height > 0 else 0.0

    return AnalysisFeatures(
        analyzer_version=ANALYZER_VERSION,
        is_heuristic=True,
        size=SizeFeatures(
            width=reported_width,
            height=reported_height,
            orientation=exif_orientation,
            aspect_ratio=_round3(aspect_ratio),
        ),
        luminance=LuminanceFeatures(
            mean=_round3(float(luminance.mean())),
            std=_round3(float(luminance.std())),
            p1=_round3(p1),
            p5=_round3(p5),
            p50=_round3(p50),
            p95=_round3(p95),
            p99=_round3(p99),
            histogram32=_histogram32(luminance),
        ),
        clipping=ClippingFeatures(
            highlights_pct=_round3(float(np.mean(luminance >= 250.0 / 255.0)) * 100.0),
            shadows_pct=_round3(float(np.mean(luminance <= 5.0 / 255.0)) * 100.0),
        ),
        color=ColorFeatures(
            mean_rgb=[_round3(float(value)) for value in rgb.reshape(-1, 3).mean(axis=0)],
            cast_estimate=_cast_estimate(rgb),
            saturation_mean=_round3(saturation_mean),
            saturation_p95=_round3(float(np.percentile(saturation, 95.0))),
        ),
        detail=DetailFeatures(
            sharpness=_sharpness(luminance),
            noise_estimate=_noise_estimate(luminance),
        ),
        composition=CompositionFeatures(
            horizon_tilt_deg=_horizon_tilt(edges),
            edgeDensityGrid3x3=_edge_density_grid(edges),
            brightness_centroid=_brightness_centroid(luminance),
        ),
        scene_hints=SceneHints(
            is_low_light=p50 < LOW_LIGHT_P50,
            is_high_key=p50 > HIGH_KEY_P50,
            is_low_key=p95 < LOW_KEY_P95,
            is_monochrome=saturation_mean < MONOCHROME_SATURATION,
        ),
    )
