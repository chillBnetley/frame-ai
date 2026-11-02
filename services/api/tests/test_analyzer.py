from __future__ import annotations

import json

import cv2
import numpy as np
import pytest

from app.imaging.analyzer import ANALYZER_VERSION, analyze
from app.imaging.loader import LoadedImage


def _loaded(rgb: np.ndarray) -> LoadedImage:
    return LoadedImage(rgb=np.ascontiguousarray(rgb.astype(np.float32)))


def _solid(
    value: float | tuple[float, float, float], size: tuple[int, int] = (80, 120)
) -> LoadedImage:
    height, width = size
    if isinstance(value, tuple):
        data = np.empty((height, width, 3), dtype=np.float32)
        data[...] = value
    else:
        data = np.full((height, width, 3), value, dtype=np.float32)
    return _loaded(data)


def _gradient(size: tuple[int, int] = (90, 160)) -> LoadedImage:
    height, width = size
    line = np.linspace(0.0, 1.0, width, dtype=np.float32)
    gray = np.repeat(line[None, :], height, axis=0)
    return _loaded(np.repeat(gray[..., None], 3, axis=2))


def _tilted_lines() -> LoadedImage:
    height, width = 180, 240
    canvas = np.full((height, width), 190, dtype=np.uint8)
    offset = int(np.tan(np.deg2rad(10.0)) * (width - 1))
    for start in range(8, 150, 24):
        cv2.line(canvas, (0, start), (width - 1, start + offset), 60, 1)
    gray = canvas.astype(np.float32) / 255.0
    return _loaded(np.repeat(gray[..., None], 3, axis=2))


def test_pure_black_and_white_hit_the_expected_extremes():
    black = analyze(_solid(0.0))
    white = analyze(_solid(1.0))

    assert black.luminance.mean == 0.0
    assert black.luminance.std == 0.0
    assert black.luminance.p99 == 0.0
    assert black.luminance.histogram32[0] == 1.0
    assert black.clipping.highlights_pct == 0.0
    assert black.clipping.shadows_pct == 100.0
    assert black.scene_hints.is_low_light
    assert black.scene_hints.is_low_key
    assert not black.scene_hints.is_high_key

    assert white.luminance.mean == 1.0
    assert white.luminance.histogram32[-1] == 1.0
    assert white.clipping.highlights_pct == 100.0
    assert white.clipping.shadows_pct == 0.0
    assert white.scene_hints.is_high_key
    assert not white.scene_hints.is_low_light
    assert not white.scene_hints.is_low_key


def test_mid_gray_does_not_trigger_high_key():
    features = analyze(_solid(0.5))

    assert features.luminance.mean == 0.5
    assert features.luminance.std == 0.0
    assert features.clipping.highlights_pct == 0.0
    assert features.clipping.shadows_pct == 0.0
    assert not features.scene_hints.is_low_light
    assert not features.scene_hints.is_high_key
    assert features.scene_hints.is_low_key
    assert features.scene_hints.is_monochrome
    assert features.color.mean_rgb == [0.5, 0.5, 0.5]

    brighter = analyze(_solid(0.65)).scene_hints
    assert not brighter.is_low_light
    assert not brighter.is_high_key
    assert not brighter.is_low_key


def test_gradient_has_wide_percentiles_and_weighted_centroid():
    features = analyze(_gradient())

    assert features.luminance.mean == pytest.approx(0.5, abs=0.01)
    assert features.luminance.p1 < 0.05
    assert features.luminance.p5 < 0.1
    assert features.luminance.p95 > 0.9
    assert features.luminance.p99 > 0.95
    assert features.composition.brightness_centroid[0] == pytest.approx(2.0 / 3.0, abs=0.02)
    assert features.composition.brightness_centroid[1] == pytest.approx(0.5, abs=0.02)
    assert max(features.composition.edge_density_grid3x3) < 0.01
    assert features.scene_hints.is_monochrome


def test_brightness_centroid_follows_a_bright_region():
    height, width = 100, 200
    data = np.zeros((height, width, 3), dtype=np.float32)
    data[30:70, 40:60] = 0.8

    features = analyze(_loaded(data))

    assert features.composition.brightness_centroid[0] == pytest.approx(
        (40 + 60) / 2.0 / width, abs=0.01
    )
    assert features.composition.brightness_centroid[1] == pytest.approx(
        (30 + 70) / 2.0 / height, abs=0.01
    )


def test_histogram_is_normalized_and_uses_at_most_three_decimals():
    features = analyze(_gradient())

    histogram = features.luminance.histogram32
    assert len(histogram) == 32
    assert sum(histogram) == pytest.approx(1.0, abs=1e-9)
    assert all(0.0 <= value <= 1.0 for value in histogram)
    assert all(abs(value * 1000 - round(value * 1000)) < 1e-9 for value in histogram)
    assert 0.02 < histogram[10] < 0.05


def test_tilted_lines_produce_a_horizon_estimate():
    features = analyze(_tilted_lines())

    assert features.composition.horizon_tilt_deg is not None
    assert 7.0 <= abs(features.composition.horizon_tilt_deg) <= 13.0
    assert sum(features.composition.edge_density_grid3x3) > 0.0


def test_featureless_gradient_reports_no_horizon():
    features = analyze(_gradient())

    assert features.composition.horizon_tilt_deg is None


def test_cast_estimates_follow_the_channel_bias():
    warm = analyze(_solid((0.6, 0.45, 0.3))).color.cast_estimate
    cool = analyze(_solid((0.3, 0.45, 0.6))).color.cast_estimate
    green = analyze(_solid((0.4, 0.55, 0.4))).color.cast_estimate
    magenta = analyze(_solid((0.55, 0.4, 0.55))).color.cast_estimate

    assert warm.temperature > 50
    assert cool.temperature < -50
    assert green.tint < -20
    assert magenta.tint > 20
    assert -100 <= warm.temperature <= 100
    assert -100 <= green.tint <= 100


def test_saturation_and_monochrome_hint():
    colorful = analyze(_solid((0.7, 0.3, 0.2)))
    gray = analyze(_gradient())

    assert colorful.color.saturation_mean > 0.5
    assert not colorful.scene_hints.is_monochrome
    assert gray.scene_hints.is_monochrome


def test_sharpness_reacts_to_edge_content():
    checker = np.indices((96, 96)).sum(axis=0) // 8 % 2
    sharp_rgb = np.repeat(
        np.where(checker == 0, 0.25, 0.75).astype(np.float32)[..., None], 3, axis=2
    )
    blurred = cv2.GaussianBlur(sharp_rgb, (0, 0), sigmaX=3.0, sigmaY=3.0)

    sharp = analyze(_loaded(sharp_rgb)).detail.sharpness
    soft = analyze(_loaded(blurred)).detail.sharpness

    assert sharp > soft
    assert 0.0 <= soft <= 1.0
    assert 0.0 <= sharp <= 1.0


def test_noise_estimate_reacts_to_grain():
    clean = _gradient()
    noisy_rgb = np.clip(
        clean.rgb + np.random.default_rng(11).normal(0.0, 0.08, clean.rgb.shape).astype(np.float32),
        0.0,
        1.0,
    )

    clean_noise = analyze(clean).detail.noise_estimate
    noisy_noise = analyze(_loaded(noisy_rgb)).detail.noise_estimate

    assert noisy_noise > clean_noise
    assert 0.0 <= clean_noise <= 1.0
    assert 0.0 <= noisy_noise <= 1.0


def test_size_reports_display_dimensions_and_orientation():
    features = analyze(_solid(0.5), display_width=3000, display_height=2000, exif_orientation=6)

    assert features.size.width == 3000
    assert features.size.height == 2000
    assert features.size.aspect_ratio == 1.5
    assert features.size.orientation == 6


def test_analysis_is_deterministic_and_contains_no_pixel_payloads():
    image = _tilted_lines()

    first = analyze(image)
    second = analyze(image)
    payload = first.model_dump(by_alias=True)

    assert first == second
    assert payload["analyzerVersion"] == ANALYZER_VERSION
    assert payload["isHeuristic"] is True
    assert "analyzerVersion" in payload
    text = json.dumps(payload).lower()
    for forbidden in ("base64", "thumbnail", "pixels", "imagedata", "bytes"):
        assert forbidden not in text
