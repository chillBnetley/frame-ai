import { CURVE_MAX_POINTS, roundTo6 } from "@/lib/recipe";
import type { CurvePoint } from "@/types/session";

export const CURVE_MIN_GAP = 0.01;

function clamp01(value: number): number {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.min(1, Math.max(0, value));
}

function makePoint(x: number, y: number): CurvePoint {
  return { x: roundTo6(clamp01(x)), y: roundTo6(clamp01(y)) };
}

function copyPoints(points: readonly CurvePoint[]): CurvePoint[] {
  return points.map((point) => ({ x: point.x, y: point.y }));
}

function tangents(x: readonly number[], y: readonly number[]): number[] {
  const count = x.length;
  const delta: number[] = [];
  for (let index = 0; index < count - 1; index += 1) {
    delta.push((y[index + 1] - y[index]) / (x[index + 1] - x[index]));
  }

  const slope = new Array<number>(count);
  slope[0] = delta[0];
  slope[count - 1] = delta[count - 2];
  for (let index = 1; index < count - 1; index += 1) {
    slope[index] = (delta[index - 1] + delta[index]) / 2;
  }

  for (let index = 0; index < delta.length; index += 1) {
    if (delta[index] === 0) {
      slope[index] = 0;
      slope[index + 1] = 0;
      continue;
    }
    let alpha = slope[index] / delta[index];
    let beta = slope[index + 1] / delta[index];
    if (alpha < 0) {
      slope[index] = 0;
      alpha = 0;
    }
    if (beta < 0) {
      slope[index + 1] = 0;
      beta = 0;
    }
    const norm = alpha * alpha + beta * beta;
    if (norm > 9) {
      const scale = 3 / Math.sqrt(norm);
      slope[index] = scale * alpha * delta[index];
      slope[index + 1] = scale * beta * delta[index];
    }
  }

  return slope;
}

export function isIdentityCurve(points: readonly CurvePoint[] | undefined): boolean {
  return !points || points.length === 0;
}

export function evaluateCurveAt(value: number, points: readonly CurvePoint[]): number {
  const clamped = clamp01(value);
  if (points.length < 2) {
    return clamped;
  }

  const x = points.map((point) => point.x);
  const y = points.map((point) => point.y);
  const slope = tangents(x, y);

  let index = -1;
  for (let candidate = 0; candidate < x.length; candidate += 1) {
    if (x[candidate] <= clamped) {
      index = candidate;
    } else {
      break;
    }
  }
  index = Math.min(Math.max(index, 0), x.length - 2);

  const width = x[index + 1] - x[index];
  const t = Math.min(1, Math.max(0, (clamped - x[index]) / width));
  const t2 = t * t;
  const t3 = t2 * t;
  const h00 = 2 * t3 - 3 * t2 + 1;
  const h10 = t3 - 2 * t2 + t;
  const h01 = -2 * t3 + 3 * t2;
  const h11 = t3 - t2;

  const result =
    h00 * y[index] +
    h10 * width * slope[index] +
    h01 * y[index + 1] +
    h11 * width * slope[index + 1];
  return clamp01(result);
}

export interface CurveSample {
  x: number;
  y: number;
}

export function sampleCurve(
  points: readonly CurvePoint[],
  samples = 65,
): CurveSample[] {
  const count = Math.max(2, Math.floor(samples));
  return Array.from({ length: count }, (_, index) => {
    const x = index / (count - 1);
    return { x, y: evaluateCurveAt(x, points) };
  });
}

export function insertCurvePoint(
  points: readonly CurvePoint[],
  x: number,
  y: number,
): CurvePoint[] {
  const base =
    points.length >= 2 ? copyPoints(points) : [makePoint(0, 0), makePoint(1, 1)];
  const next = makePoint(x, y);
  if (base.length >= CURVE_MAX_POINTS) {
    return base;
  }
  if (base.some((point) => Math.abs(point.x - next.x) < CURVE_MIN_GAP)) {
    return base;
  }
  return [...base, next].sort((left, right) => left.x - right.x);
}

export function moveCurvePoint(
  points: readonly CurvePoint[],
  index: number,
  x: number,
  y: number,
): CurvePoint[] {
  const next = copyPoints(points);
  if (index < 0 || index >= next.length) {
    return next;
  }

  if (index === 0) {
    next[0] = makePoint(0, y);
    return next;
  }
  if (index === next.length - 1) {
    next[index] = makePoint(1, y);
    return next;
  }

  const lower = next[index - 1].x + CURVE_MIN_GAP;
  const upper = next[index + 1].x - CURVE_MIN_GAP;
  const boundedX = upper < lower ? next[index].x : Math.min(upper, Math.max(lower, x));
  next[index] = makePoint(boundedX, y);
  return next;
}

export function deleteCurvePoint(
  points: readonly CurvePoint[],
  index: number,
): CurvePoint[] {
  if (index <= 0 || index >= points.length - 1) {
    return copyPoints(points);
  }
  return points.filter((_, position) => position !== index).map((point) => ({ ...point }));
}
