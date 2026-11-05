from __future__ import annotations

import math

import numpy as np
import pytest

from app.imaging.geometry import crop_bounds, rotation_matrix, rotation_target_size
from app.imaging.local_masks import mask_weights
from app.models.recipe import Crop, UserMask


def _mask(**overrides: object) -> UserMask:
    payload: dict[str, object] = {
        "id": "mask_001",
        "x": 0.2,
        "y": 0.3,
        "width": 0.4,
        "height": 0.2,
        "feather": 0,
        "opacity": 100,
    }
    payload.update(overrides)
    return UserMask.model_validate(payload)


def _at(weights: np.ndarray, x: float, y: float) -> float:
    height, width = weights.shape
    column = min(max(int(x * width), 0), width - 1)
    row = min(max(int(y * height), 0), height - 1)
    return float(weights[row, column])


def _weights(
    mask: UserMask,
    *,
    width: int = 100,
    height: int = 100,
    rotation_deg: float = 0.0,
    crop: Crop | None = None,
) -> np.ndarray:
    target_width, target_height = rotation_target_size(width, height, rotation_deg)
    x0, y0, x1, y1 = crop_bounds(crop, target_width, target_height)
    return mask_weights(
        mask,
        output_width=x1 - x0,
        output_height=y1 - y0,
        source_width=width,
        source_height=height,
        rotation_deg=rotation_deg,
        crop=crop,
    )


def test_rectangle_weights_without_geometry():
    weights = _weights(_mask())
    assert _at(weights, 0.4, 0.4) == pytest.approx(1.0)
    assert _at(weights, 0.21, 0.31) == pytest.approx(1.0)
    assert _at(weights, 0.1, 0.4) == 0.0
    assert _at(weights, 0.7, 0.4) == 0.0
    assert _at(weights, 0.4, 0.6) == 0.0


def test_ellipse_weights_without_geometry():
    mask = _mask(x=0.25, y=0.25, width=0.5, height=0.5, shape="ellipse")
    weights = _weights(mask)
    assert _at(weights, 0.5, 0.5) == pytest.approx(1.0)
    assert _at(weights, 0.26, 0.26) == 0.0
    assert _at(weights, 0.9, 0.9) == 0.0


def test_feather_is_inside_and_monotonic():
    mask = _mask(x=0.2, y=0.2, width=0.6, height=0.6, feather=30)
    weights = _weights(mask)
    row = weights[50]
    values = [float(row[column]) for column in range(30, 81, 5)]
    assert values[0] == pytest.approx(1.0)
    assert all(left >= right - 1e-6 for left, right in zip(values[:-1], values[1:], strict=True))
    assert values[-1] == pytest.approx(0.0, abs=1e-6)
    assert _at(weights, 0.81, 0.5) == 0.0


def test_zero_feather_is_binary():
    weights = _weights(_mask(feather=0))
    assert set(np.unique(weights).tolist()) <= {0.0, 1.0}


def test_inverted_and_opacity():
    mask = _mask(feather=0, inverted=True, opacity=40)
    weights = _weights(mask)
    assert _at(weights, 0.4, 0.4) == pytest.approx(0.0)
    assert _at(weights, 0.9, 0.9) == pytest.approx(0.4)


def test_opacity_zero_has_no_weight():
    weights = _weights(_mask(opacity=0))
    assert float(weights.max()) == 0.0


def test_full_feather_tapers_from_center():
    mask = _mask(x=0.1, y=0.1, width=0.8, height=0.8, feather=100)
    weights = _weights(mask)
    assert _at(weights, 0.5, 0.5) == pytest.approx(1.0, abs=0.01)
    assert _at(weights, 0.89, 0.5) < 0.1


@pytest.mark.parametrize("rotation_deg", [7.5, -7.5, 15.0])
@pytest.mark.parametrize(
    "crop",
    [
        None,
        Crop.model_validate({"x": 0.1, "y": 0.08, "w": 0.8, "h": 0.84}),
    ],
)
def test_rotation_and_crop_track_the_mask_center(rotation_deg: float, crop: Crop | None):
    source_width, source_height = 400, 300
    mask = _mask(x=0.35, y=0.3, width=0.3, height=0.4, shape="ellipse", feather=0)
    target_width, target_height = rotation_target_size(source_width, source_height, rotation_deg)
    x0, y0, x1, y1 = crop_bounds(crop, target_width, target_height)
    weights = mask_weights(
        mask,
        output_width=x1 - x0,
        output_height=y1 - y0,
        source_width=source_width,
        source_height=source_height,
        rotation_deg=rotation_deg,
        crop=crop,
    )

    center_x = mask.x + mask.width / 2.0
    center_y = mask.y + mask.height / 2.0
    source_x = center_x * source_width - 0.5
    source_y = center_y * source_height - 0.5
    matrix = rotation_matrix(source_width, source_height, rotation_deg, target_width, target_height)
    target_x = matrix[0, 0] * source_x + matrix[0, 1] * source_y + matrix[0, 2]
    target_y = matrix[1, 0] * source_x + matrix[1, 1] * source_y + matrix[1, 2]
    column = int(round(target_x - x0))
    row = int(round(target_y - y0))
    assert 0 <= row < weights.shape[0]
    assert 0 <= column < weights.shape[1]
    assert weights[row, column] > 0.99

    far_x = (center_x + 0.4) * source_width - 0.5
    far_y = center_y * source_height - 0.5
    target_far_x = matrix[0, 0] * far_x + matrix[0, 1] * far_y + matrix[0, 2]
    target_far_y = matrix[1, 0] * far_x + matrix[1, 1] * far_y + matrix[1, 2]
    far_column = int(round(target_far_x - x0))
    far_row = int(round(target_far_y - y0))
    if 0 <= far_row < weights.shape[0] and 0 <= far_column < weights.shape[1]:
        assert weights[far_row, far_column] == 0.0


def test_weights_are_resolution_independent():
    mask = _mask(x=0.2, y=0.15, width=0.5, height=0.55, shape="ellipse", feather=30)
    small = _weights(mask, width=400, height=300, rotation_deg=7.5)
    large = _weights(mask, width=1600, height=1200, rotation_deg=7.5)
    for x, y in ((0.5, 0.4), (0.2, 0.2), (0.7, 0.65), (0.05, 0.95)):
        assert abs(_at(small, x, y) - _at(large, x, y)) <= 0.03


def test_mask_entirely_outside_crop_is_zero():
    mask = _mask(x=0.01, y=0.01, width=0.05, height=0.05)
    crop = Crop.model_validate({"x": 0.5, "y": 0.5, "w": 0.4, "h": 0.4})
    weights = _weights(mask, crop=crop)
    assert float(weights.max()) == 0.0


def test_boundary_values_are_supported():
    mask = _mask(x=0.4, y=0.4, width=0.6, height=0.6, feather=100, opacity=100)
    weights = _weights(mask)
    assert _at(weights, 0.7, 0.7) == pytest.approx(1.0, abs=0.01)
    assert math.isfinite(float(weights.sum()))


def test_mismatched_output_dimensions_raise():
    with pytest.raises(ValueError):
        mask_weights(
            _mask(),
            output_width=50,
            output_height=50,
            source_width=100,
            source_height=100,
            rotation_deg=0.0,
            crop=None,
        )
