from __future__ import annotations

import json
import re

import cv2
import numpy as np
import pytest

from app.ai.contracts import MeasurementSummary
from app.analysis.features import FEATURE_SET_VERSION, extract_features
from app.imaging.loader import LoadedImage

HEX_PATTERN = re.compile(r"^#[0-9A-F]{6}$")


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


def test_black_and_white_hit_the_expected_extremes():
    black = extract_features(_solid(0.0))
    white = extract_features(_solid(1.0))

    assert black.luminance_mean == 0.0
    assert black.luminance_std == 0.0
    assert black.luminance_p99 == 0.0
    assert black.histogram32[0] == 1.0
    assert black.highlights_pct == 0.0
    assert black.shadows_pct == 100.0
    assert black.dominant_colors == ("#000000",)
    assert black.color_richness == 0.0
    assert black.saturation_mean == 0.0

    assert white.luminance_mean == 1.0
    assert white.histogram32[-1] == 1.0
    assert white.highlights_pct == 100.0
    assert white.shadows_pct == 0.0
    assert white.dominant_colors == ("#FFFFFF",)
    assert white.color_richness == 0.0


def test_mid_gray_is_neutral_and_reports_its_shade():
    features = extract_features(_solid(0.5))

    assert features.luminance_mean == 0.5
    assert features.luminance_p50 == 0.5
    assert features.luminance_std == 0.0
    assert features.cast_temperature == 0.0
    assert features.cast_tint == 0.0
    assert features.saturation_mean == 0.0
    assert features.color_richness == 0.0
    assert features.dominant_colors == ("#808080",)


def test_gradient_has_ordered_percentiles_and_weighted_centroid():
    features = extract_features(_gradient())

    assert features.luminance_mean == pytest.approx(0.5, abs=0.01)
    assert features.luminance_p1 < features.luminance_p5 < features.luminance_p50
    assert features.luminance_p50 < features.luminance_p95 < features.luminance_p99
    assert features.brightness_centroid_x == pytest.approx(2.0 / 3.0, abs=0.02)
    assert features.brightness_centroid_y == pytest.approx(0.5, abs=0.02)
    assert features.horizon_tilt_deg is None


def test_histogram_is_normalized_to_32_integer_bins():
    features = extract_features(_gradient())

    histogram = features.histogram32
    assert len(histogram) == 32
    assert sum(histogram) == pytest.approx(1.0, abs=1e-9)
    assert all(0.0 <= value <= 1.0 for value in histogram)
    assert all(abs(value * 1000 - round(value * 1000)) < 1e-9 for value in histogram)


def test_cast_estimates_follow_channel_bias():
    warm = extract_features(_solid((0.6, 0.45, 0.3)))
    cool = extract_features(_solid((0.3, 0.45, 0.6)))
    green = extract_features(_solid((0.4, 0.55, 0.4)))
    magenta = extract_features(_solid((0.55, 0.4, 0.55)))

    assert warm.cast_temperature > 50
    assert cool.cast_temperature < -50
    assert green.cast_tint < -20
    assert magenta.cast_tint > 20
    assert -100 <= warm.cast_temperature <= 100


def test_saturation_and_color_richness_react_to_color():
    colorful = extract_features(_solid((0.7, 0.3, 0.2)))
    muted = extract_features(_solid((0.52, 0.5, 0.5)))
    gray = extract_features(_gradient())

    assert colorful.saturation_mean > 0.5
    assert colorful.saturation_p95 >= colorful.saturation_mean
    assert muted.saturation_mean < 0.1
    assert colorful.color_richness > gray.color_richness
    assert gray.color_richness == 0.0


def test_sharpness_reacts_to_edge_content():
    checker = np.indices((96, 96)).sum(axis=0) // 8 % 2
    sharp_rgb = np.repeat(
        np.where(checker == 0, 0.25, 0.75).astype(np.float32)[..., None], 3, axis=2
    )
    blurred = cv2.GaussianBlur(sharp_rgb, (0, 0), sigmaX=3.0, sigmaY=3.0)

    sharp = extract_features(_loaded(sharp_rgb)).sharpness
    soft = extract_features(_loaded(blurred)).sharpness

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

    clean_noise = extract_features(clean).noise_estimate
    noisy_noise = extract_features(_loaded(noisy_rgb)).noise_estimate

    assert noisy_noise > clean_noise
    assert 0.0 <= clean_noise <= 1.0
    assert 0.0 <= noisy_noise <= 1.0


def test_dominant_colors_merge_similar_shades_deterministically():
    data = np.zeros((40, 60, 3), dtype=np.float32)
    data[:, :30] = np.array((250, 0, 0), dtype=np.float32) / 255.0
    data[:, 30:] = np.array((252, 2, 2), dtype=np.float32) / 255.0

    first = extract_features(_loaded(data))
    second = extract_features(_loaded(data))

    assert first.dominant_colors == second.dominant_colors == ("#FF0000",)


def test_dominant_colors_are_capped_and_well_formed():
    colors = [
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
        (255, 255, 255),
        (0, 0, 0),
        (255, 255, 0),
    ]
    data = np.zeros((60, 60, 3), dtype=np.float32)
    for index, color in enumerate(colors):
        data[:, index * 10 : (index + 1) * 10] = np.array(color, dtype=np.float32) / 255.0

    features = extract_features(_loaded(data))

    assert 1 <= len(features.dominant_colors) <= 5
    assert all(HEX_PATTERN.match(color) for color in features.dominant_colors)
    assert len(set(features.dominant_colors)) == len(features.dominant_colors)


def test_composition_fields_are_complete():
    features = extract_features(_tilted_lines())

    assert features.horizon_tilt_deg is not None
    assert 7.0 <= abs(features.horizon_tilt_deg) <= 13.0
    assert len(features.edge_density_grid_3x3) == 9
    assert all(0.0 <= value <= 1.0 for value in features.edge_density_grid_3x3)
    assert sum(features.edge_density_grid_3x3) > 0.0
    assert 0.0 <= features.brightness_centroid_x <= 1.0
    assert 0.0 <= features.brightness_centroid_y <= 1.0


def test_display_dimensions_and_version_are_reported():
    features = extract_features(
        _solid(0.5),
        display_width=3000,
        display_height=2000,
    )

    assert isinstance(features, MeasurementSummary)
    assert features.feature_set_version == FEATURE_SET_VERSION
    assert (features.width, features.height) == (3000, 2000)
    assert features.aspect_ratio == 1.5


def test_color_and_tone_histograms_are_normalized_and_deterministic():
    image = _solid((0.7, 0.3, 0.2))
    first = extract_features(image)
    second = extract_features(image)

    assert first.rgb_histogram == second.rgb_histogram
    assert len(first.rgb_histogram) == 3
    assert all(len(channel) == 32 for channel in first.rgb_histogram)
    assert all(sum(channel) == pytest.approx(1.0, abs=1e-6) for channel in first.rgb_histogram)

    assert len(first.hsv_histogram) == 3
    assert [len(channel) for channel in first.hsv_histogram] == [16, 8, 8]
    assert all(sum(channel) == pytest.approx(1.0, abs=1e-6) for channel in first.hsv_histogram)

    assert first.saturation_p10 <= first.saturation_p50 <= first.saturation_p90
    assert first.color_concentration == pytest.approx(1.0, abs=1e-6)


def test_gradient_anisotropy_detects_directional_structure():
    height, width = 120, 160
    stripes = np.tile((np.arange(width) // 8 % 2).astype(np.float32), (height, 1))
    striped = _loaded(np.repeat(stripes[..., None], 3, axis=2))

    assert extract_features(_solid(0.5)).gradient_anisotropy == 0.0
    assert extract_features(striped).gradient_anisotropy > 0.9


def test_color_concentration_drops_for_scattered_palette():
    solid = extract_features(_solid((0.2, 0.4, 0.6)))
    colors = [
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
        (255, 255, 255),
        (0, 0, 0),
        (255, 255, 0),
    ]
    data = np.zeros((60, 60, 3), dtype=np.float32)
    for index, color in enumerate(colors):
        data[:, index * 10 : (index + 1) * 10] = np.array(color, dtype=np.float32) / 255.0

    scattered = extract_features(_loaded(data))

    assert solid.color_concentration > scattered.color_concentration
    assert 0.0 < scattered.color_concentration <= 1.0


@pytest.mark.parametrize(
    "image",
    [
        _solid(0.0),
        _solid(1.0),
        _solid(0.5),
        _gradient(),
        _tilted_lines(),
    ],
)
def test_all_ranges_hold_for_synthetic_images(image: LoadedImage):
    features = extract_features(image)

    for value in (
        features.luminance_mean,
        features.luminance_std,
        features.luminance_p1,
        features.luminance_p5,
        features.luminance_p50,
        features.luminance_p95,
        features.luminance_p99,
        features.saturation_mean,
        features.saturation_p95,
        features.color_richness,
        features.noise_estimate,
        features.saturation_p10,
        features.saturation_p50,
        features.saturation_p90,
        features.color_concentration,
        features.gradient_anisotropy,
    ):
        assert 0.0 <= value <= 1.0
    assert 0.0 <= features.highlights_pct <= 100.0
    assert 0.0 <= features.shadows_pct <= 100.0
    assert features.sharpness >= 0.0


def test_features_are_deterministic_and_exclude_pixel_payloads():
    image = _tilted_lines()

    first = extract_features(image)
    second = extract_features(image)
    payload = first.model_dump(mode="json", by_alias=True)

    assert first == second
    assert payload["featureSetVersion"] == FEATURE_SET_VERSION
    text = json.dumps(payload).lower()
    for forbidden in ("base64", "thumbnail", "pixels", "imagedata"):
        assert forbidden not in text
