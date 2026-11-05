from __future__ import annotations

import numpy as np
import pytest

from app.imaging.curves import (
    CURVE_LUT_STEPS,
    _curve_arrays,
    _hermite_values,
    apply_curves,
    evaluate_curve,
)
from app.imaging.output import to_uint8
from app.models.recipe import CURVE_MAX_POINTS, CurvePoint, CurveSet


def _points(*pairs: tuple[float, float]) -> tuple[CurvePoint, ...]:
    return tuple(CurvePoint(x=x, y=y) for x, y in pairs)


def _ramp(size: int = 512) -> np.ndarray:
    return np.linspace(0.0, 1.0, size, dtype=np.float32)


def test_empty_and_identity_curves_do_not_change_values():
    values = _ramp()

    assert evaluate_curve(values, ()) is values
    assert np.allclose(evaluate_curve(values, _points((0, 0), (1, 1))), values, atol=1e-6)


def test_midtone_lift_and_darken():
    lift = _points((0, 0), (0.5, 0.65), (1, 1))
    darken = _points((0, 0), (0.5, 0.35), (1, 1))

    assert float(evaluate_curve(np.array([0.5], dtype=np.float32), lift)[0]) == pytest.approx(
        0.65, abs=1e-5
    )
    assert float(evaluate_curve(np.array([0.5], dtype=np.float32), darken)[0]) == pytest.approx(
        0.35, abs=1e-5
    )
    assert float(evaluate_curve(np.array([0.25], dtype=np.float32), lift)[0]) > 0.25
    assert float(evaluate_curve(np.array([0.75], dtype=np.float32), darken)[0]) < 0.75


def test_black_lift_and_highlight_reduction():
    curve = _points((0, 0.1), (1, 0.9))

    result = evaluate_curve(np.array([0.0, 0.5, 1.0], dtype=np.float32), curve)

    assert result[0] == pytest.approx(0.1)
    assert result[2] == pytest.approx(0.9)
    assert result[1] == pytest.approx(0.5, abs=1e-5)


def test_curve_extrapolates_endpoint_tangents_outside_its_domain():
    curve = _points((0.2, 0.3), (0.8, 0.7))

    result = evaluate_curve(np.array([0.0, 0.2, 0.8, 1.0], dtype=np.float32), curve)

    # Two nodes give matching endpoint tangents (slope 2/3), so the hanging
    # curve is a straight line: 0.3 - 2/3*0.2 = 1/6 and 0.7 + 2/3*0.2 = 5/6.
    half_step = 1.0 / (2.0 * 255.0)
    assert result[0] == pytest.approx(1.0 / 6.0, abs=half_step)
    assert result[1] == pytest.approx(0.3, abs=half_step)
    assert result[2] == pytest.approx(0.7, abs=half_step)
    assert result[3] == pytest.approx(5.0 / 6.0, abs=half_step)


def test_hanging_curve_extrapolation_is_continuous_and_monotonic():
    curve = _points((0.15, 0.25), (0.45, 0.5), (0.85, 0.8))
    ramp = _ramp(4096)

    result = evaluate_curve(ramp, curve)

    assert np.all(np.diff(result) >= -1e-6)
    # No flat "hold" at either end: both extrapolated regions keep moving.
    assert float(result[0]) < 0.25
    assert float(result[-1]) > 0.8
    for node in (0.15, 0.45, 0.85):
        left = float(evaluate_curve(np.array([node - 1e-4], dtype=np.float32), curve)[0])
        right = float(evaluate_curve(np.array([node + 1e-4], dtype=np.float32), curve)[0])
        assert abs(left - right) < 1e-3


def test_channel_curve_only_changes_that_channel():
    rgb = np.tile(np.array([0.2, 0.4, 0.6], dtype=np.float32), (4, 4, 1))
    curve = CurveSet(red=_points((0, 0), (0.5, 0.7), (1, 1)))

    adjusted = apply_curves(rgb, curve)

    assert np.array_equal(adjusted[..., 1], rgb[..., 1])
    assert np.array_equal(adjusted[..., 2], rgb[..., 2])
    assert not np.array_equal(adjusted[..., 0], rgb[..., 0])


def test_master_curve_runs_before_channel_curves():
    rgb = np.full((2, 2, 3), 0.5, dtype=np.float32)
    curve = CurveSet(
        master=_points((0, 0), (0.5, 0.6), (1, 1)),
        red=_points((0, 0), (0.6, 0.4), (1, 1)),
    )

    adjusted = apply_curves(rgb, curve)

    assert adjusted[0, 0, 0] == pytest.approx(0.4, abs=1e-5)
    assert adjusted[0, 0, 1] == pytest.approx(0.6, abs=1e-5)
    assert adjusted[0, 0, 2] == pytest.approx(0.6, abs=1e-5)


@pytest.mark.parametrize(
    "points",
    [
        ((0.0, 0.0), (0.25, 0.15), (0.5, 0.6), (0.75, 0.85), (1.0, 1.0)),
        ((0.0, 0.05), (0.2, 0.2), (0.8, 0.8), (1.0, 0.95)),
    ],
)
def test_monotonic_points_produce_monotonic_curve(points: tuple[tuple[float, float], ...]):
    curve = _points(*points)
    result = evaluate_curve(_ramp(2048), curve)

    assert np.all(np.diff(result) >= -1e-6)


@pytest.mark.parametrize(
    "points",
    [
        ((0.0, 0.0), (0.4, 0.8), (0.6, 0.3), (1.0, 0.9)),
        ((0.0, 0.2), (0.25, 0.1), (0.5, 0.9), (0.75, 0.4), (1.0, 0.7)),
    ],
)
def test_local_extrema_do_not_overshoot_between_nodes(
    points: tuple[tuple[float, float], ...],
):
    curve = _points(*points)
    samples = evaluate_curve(_ramp(4096), curve)
    xs = np.array([point[0] for point in points], dtype=np.float32)

    for index in range(len(points) - 1):
        mask = (xs[index] <= _ramp(4096)) & (_ramp(4096) <= xs[index + 1])
        low = min(points[index][1], points[index + 1][1])
        high = max(points[index][1], points[index + 1][1])
        assert float(samples[mask].min()) >= low - 1e-6
        assert float(samples[mask].max()) <= high + 1e-6


def test_extreme_and_dense_curves_stay_finite_and_bounded():
    dense = tuple(
        CurvePoint(
            x=round(index / 31.0, 6),
            y=round(0.5 + 0.5 * float(np.sin(index)) * 0.9, 6),
        )
        for index in range(32)
    )

    result = evaluate_curve(_ramp(1024), dense)

    assert np.all(np.isfinite(result))
    assert float(result.min()) >= 0.0
    assert float(result.max()) <= 1.0


def test_apply_curves_does_not_mutate_the_input():
    rgb = np.full((2, 2, 3), 0.5, dtype=np.float32)
    original = rgb.copy()

    apply_curves(rgb, CurveSet(master=_points((0, 0), (0.5, 0.7), (1, 1))))

    assert np.array_equal(rgb, original)


def test_apply_curves_clips_inputs_outside_the_unit_range():
    rgb = np.array([[[-0.5, 0.5, 1.5]]], dtype=np.float32)
    curve = CurveSet(master=_points((0, 0.1), (1, 0.9)))

    adjusted = apply_curves(rgb, curve)

    assert adjusted[0, 0, 0] == pytest.approx(0.1)
    assert adjusted[0, 0, 1] == pytest.approx(0.5, abs=1e-5)
    assert adjusted[0, 0, 2] == pytest.approx(0.9)


def _random_curve_nodes(rng: np.random.Generator, count: int) -> tuple[CurvePoint, ...]:
    slot = 1.0 / count
    jitter = (rng.random(count) - 0.5) * 0.4 * slot
    xs = np.unique(np.round(np.clip((np.arange(count) + 0.5) * slot + jitter, 0.0, 1.0), 6))
    ys = np.round(rng.random(xs.size), 6)
    return tuple(CurvePoint(x=float(x), y=float(y)) for x, y in zip(xs, ys, strict=True))


def test_lut_matches_hermite_within_half_step():
    rng = np.random.default_rng(20261105)
    samples = np.linspace(0.0, 1.0, 10_000, dtype=np.float32)
    worst = 0.0

    for _ in range(10_000):
        count = int(rng.integers(2, CURVE_MAX_POINTS + 1))
        points = _random_curve_nodes(rng, count)
        arrays = _curve_arrays(points)
        assert arrays is not None
        reference = _hermite_values(samples, *arrays)
        actual = evaluate_curve(samples, points)
        worst = max(worst, float(np.max(np.abs(reference - actual))))

    assert worst < 1.0 / (2.0 * 255.0)


def test_lut_is_monotonic_when_curve_is_monotonic():
    curve = _points((0, 0), (0.15, 0.05), (0.4, 0.3), (0.7, 0.72), (1, 1))

    lut = evaluate_curve(np.linspace(0.0, 1.0, CURVE_LUT_STEPS, dtype=np.float32), curve)

    assert np.all(np.diff(lut) >= 0.0)


def test_extreme_input_stays_in_range():
    curve = _points((0, 0.2), (0.5, 0.9), (1, 0.1))
    values = np.array([-5.0, -0.001, 0.0, 0.5, 1.0, 1.001, 5.0, 3e38], dtype=np.float32)

    result = evaluate_curve(values, curve)

    assert np.all(np.isfinite(result))
    assert float(result.min()) >= 0.0
    assert float(result.max()) <= 1.0


def test_non_finite_input_does_not_crash_and_quantizes_safely():
    curve = _points((0, 0), (1, 1))
    values = np.array([np.nan, np.inf, -np.inf, 0.5], dtype=np.float32)

    result = evaluate_curve(values, curve)

    assert result.shape == values.shape
    assert to_uint8(result).reshape(-1).tolist() == [0, 255, 0, 128]
