from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from app.models.recipe import CurvePoint, CurveSet

RgbArray = NDArray[np.float32]

CURVE_LUT_STEPS = 8192
_LUT_GRID = np.linspace(np.float32(0.0), np.float32(1.0), CURVE_LUT_STEPS, dtype=np.float32)


def _curve_arrays(
    points: Sequence[CurvePoint],
) -> tuple[NDArray[np.float32], NDArray[np.float32], NDArray[np.float32]] | None:
    if len(points) < 2:
        return None

    x = np.array([point.x for point in points], dtype=np.float32)
    y = np.array([point.y for point in points], dtype=np.float32)
    h = np.diff(x)
    if np.any(h <= 0):
        return None

    delta = np.diff(y) / h
    tangent = np.empty_like(y)
    tangent[0] = delta[0]
    tangent[-1] = delta[-1]
    if len(y) > 2:
        tangent[1:-1] = (delta[:-1] + delta[1:]) / np.float32(2.0)

    for index in range(len(delta)):
        if delta[index] == 0:
            tangent[index] = 0
            tangent[index + 1] = 0
            continue
        alpha = float(tangent[index] / delta[index])
        beta = float(tangent[index + 1] / delta[index])
        if alpha < 0:
            tangent[index] = 0
            alpha = 0.0
        if beta < 0:
            tangent[index + 1] = 0
            beta = 0.0
        norm = alpha * alpha + beta * beta
        if norm > 9.0:
            scale = 3.0 / float(np.sqrt(norm))
            tangent[index] = np.float32(scale * alpha) * delta[index]
            tangent[index + 1] = np.float32(scale * beta) * delta[index]

    return x, y, tangent


def _hermite_values(
    values: NDArray[np.float32],
    x: NDArray[np.float32],
    y: NDArray[np.float32],
    tangent: NDArray[np.float32],
) -> NDArray[np.float32]:
    clamped = np.clip(values, np.float32(0.0), np.float32(1.0))
    index = np.searchsorted(x, clamped, side="right") - 1
    index = np.clip(index, 0, len(x) - 2)

    width = np.diff(x)[index]
    t = np.clip((clamped - x[index]) / width, np.float32(0.0), np.float32(1.0))
    t2 = t * t
    t3 = t2 * t
    h00 = np.float32(2.0) * t3 - np.float32(3.0) * t2 + np.float32(1.0)
    h10 = t3 - np.float32(2.0) * t2 + t
    h01 = np.float32(-2.0) * t3 + np.float32(3.0) * t2
    h11 = t3 - t2

    result = (
        h00 * y[:-1][index]
        + h10 * width * tangent[:-1][index]
        + h01 * y[1:][index]
        + h11 * width * tangent[1:][index]
    )
    # Outside the node domain, extend along the endpoint tangent instead of
    # holding the endpoint value flat.  A curve that does not touch the edges
    # then keeps its slope into the shadows/highlights, like mainstream tools.
    below = clamped < x[0]
    above = clamped > x[-1]
    if np.any(below):
        result = np.where(below, y[0] + tangent[0] * (clamped - x[0]), result)
    if np.any(above):
        result = np.where(above, y[-1] + tangent[-1] * (clamped - x[-1]), result)
    return np.ascontiguousarray(np.clip(result, np.float32(0.0), np.float32(1.0)))


def _curve_lut(points: Sequence[CurvePoint]) -> NDArray[np.float32] | None:
    arrays = _curve_arrays(points)
    if arrays is None:
        return None
    x, y, tangent = arrays
    return _hermite_values(_LUT_GRID, x, y, tangent)


def evaluate_curve(
    values: NDArray[np.float32],
    points: Sequence[CurvePoint],
) -> NDArray[np.float32]:
    lut = _curve_lut(points)
    if lut is None:
        return values

    if not np.isfinite(values).all():
        # NaN has no defined int cast; clamp it to black and the infinities to
        # the ends so a bad upstream pixel cannot index outside the LUT.
        values = np.nan_to_num(values, nan=0.0, posinf=1.0, neginf=0.0)
    scaled = np.clip(values, np.float32(0.0), np.float32(1.0))
    scaled *= np.float32(CURVE_LUT_STEPS - 1)
    base = scaled.astype(np.int32)
    np.minimum(base, CURVE_LUT_STEPS - 2, out=base)
    np.subtract(scaled, base, out=scaled)
    lower = lut[base]
    np.add(base, 1, out=base)
    upper = lut[base]
    np.subtract(upper, lower, out=upper)
    np.multiply(upper, scaled, out=upper)
    np.add(upper, lower, out=upper)
    np.clip(upper, np.float32(0.0), np.float32(1.0), out=upper)
    return np.ascontiguousarray(upper)


def apply_curves(rgb: RgbArray, curve: CurveSet) -> RgbArray:
    if not (curve.master or curve.red or curve.green or curve.blue):
        return rgb

    result = np.array(rgb, dtype=np.float32, copy=True)
    if curve.master:
        result = evaluate_curve(result, curve.master)
    for channel, points in enumerate((curve.red, curve.green, curve.blue)):
        if points:
            result[..., channel] = evaluate_curve(result[..., channel], points)
    np.clip(result, np.float32(0.0), np.float32(1.0), out=result)
    return np.ascontiguousarray(result)
