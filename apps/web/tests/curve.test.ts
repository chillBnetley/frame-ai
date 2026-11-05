import { describe, expect, it } from "vitest";

import {
  CURVE_MIN_GAP,
  deleteCurvePoint,
  evaluateCurveAt,
  insertCurvePoint,
  isIdentityCurve,
  moveCurvePoint,
  sampleCurve,
} from "@/lib/curve";
import { CURVE_MAX_POINTS } from "@/lib/recipe";
import type { CurvePoint } from "@/types/session";

function points(...pairs: [number, number][]): CurvePoint[] {
  return pairs.map(([x, y]) => ({ x, y }));
}

describe("curve evaluation", () => {
  it("treats an empty curve as the identity", () => {
    expect(isIdentityCurve([])).toBe(true);
    expect(isIdentityCurve(points([0, 0], [1, 1]))).toBe(false);
    for (const value of [0, 0.17, 0.5, 0.83, 1]) {
      expect(evaluateCurveAt(value, [])).toBeCloseTo(value, 10);
    }
  });

  it("keeps a two-point identity curve unchanged", () => {
    const identity = points([0, 0], [1, 1]);
    for (const value of [0, 0.2, 0.5, 0.8, 1]) {
      expect(evaluateCurveAt(value, identity)).toBeCloseTo(value, 6);
    }
  });

  it("lifts and darkens midtones", () => {
    const lifted = points([0, 0], [0.5, 0.7], [1, 1]);
    const darkened = points([0, 0], [0.5, 0.3], [1, 1]);

    expect(evaluateCurveAt(0.5, lifted)).toBeCloseTo(0.7, 6);
    expect(evaluateCurveAt(0.25, lifted)).toBeGreaterThan(0.25);
    expect(evaluateCurveAt(0.5, darkened)).toBeCloseTo(0.3, 6);
    expect(evaluateCurveAt(0.25, darkened)).toBeLessThan(0.25);
  });

  it("lifts blacks and pulls down highlights at the endpoints", () => {
    const liftedBlack = points([0, 0.1], [1, 1]);
    const softHighlight = points([0, 0], [1, 0.9]);

    expect(evaluateCurveAt(0, liftedBlack)).toBeCloseTo(0.1, 6);
    expect(evaluateCurveAt(1, softHighlight)).toBeCloseTo(0.9, 6);
    expect(evaluateCurveAt(-0.5, liftedBlack)).toBeCloseTo(0.1, 6);
    expect(evaluateCurveAt(1.5, softHighlight)).toBeCloseTo(0.9, 6);
  });

  it("stays monotonic without overshoot for monotonic control points", () => {
    const monotonic = points([0, 0], [0.25, 0.1], [0.5, 0.7], [0.75, 0.8], [1, 1]);
    const sample = sampleCurve(monotonic, 201);

    for (let index = 1; index < sample.length; index += 1) {
      expect(sample[index].y).toBeGreaterThanOrEqual(sample[index - 1].y - 1e-9);
      expect(sample[index].y).toBeGreaterThanOrEqual(0);
      expect(sample[index].y).toBeLessThanOrEqual(1);
    }
  });

  it("does not oscillate around a local extremum", () => {
    const peaked = points([0, 0], [0.4, 0.8], [0.6, 0.2], [1, 1]);
    const sample = sampleCurve(peaked, 401);

    for (const entry of sample) {
      if (entry.x > 0.4 && entry.x < 0.6) {
        expect(entry.y).toBeGreaterThanOrEqual(0.2 - 1e-9);
        expect(entry.y).toBeLessThanOrEqual(0.8 + 1e-9);
      }
    }
  });

  it("clips samples and values to the unit range", () => {
    const steep = points([0, 0], [0.5, 1], [1, 0]);
    for (const entry of sampleCurve(steep, 128)) {
      expect(entry.y).toBeGreaterThanOrEqual(0);
      expect(entry.y).toBeLessThanOrEqual(1);
      expect(Number.isFinite(entry.y)).toBe(true);
    }
    expect(evaluateCurveAt(-1, steep)).toBe(0);
    expect(evaluateCurveAt(2, steep)).toBe(0);
  });
});

describe("curve point editing", () => {
  it("materializes endpoints when inserting into an empty curve", () => {
    const next = insertCurvePoint([], 0.4, 0.6);

    expect(next).toEqual(points([0, 0], [0.4, 0.6], [1, 1]));
  });

  it("inserts in sorted order with six decimals", () => {
    const next = insertCurvePoint(points([0, 0], [1, 1]), 0.333333333, 0.666666666);

    expect(next.map((point) => point.x)).toEqual([0, 0.333333, 1]);
    expect(next[1]?.y).toBe(0.666667);
  });

  it("rejects points that collide with an existing x", () => {
    const curve = points([0, 0], [0.5, 0.5], [1, 1]);

    expect(insertCurvePoint(curve, 0.5 + CURVE_MIN_GAP / 2, 0.2)).toEqual(curve);
    expect(insertCurvePoint(curve, 0, 0.9)).toEqual(curve);
  });

  it("never exceeds the point limit", () => {
    const dense = Array.from({ length: CURVE_MAX_POINTS }, (_, index) => ({
      x: Math.round((index / (CURVE_MAX_POINTS - 1)) * 1e6) / 1e6,
      y: index / (CURVE_MAX_POINTS - 1),
    }));

    expect(insertCurvePoint(dense, 0.5000004, 0.5)).toHaveLength(CURVE_MAX_POINTS);
  });

  it("clamps internal nodes between their neighbours", () => {
    const curve = points([0, 0], [0.4, 0.5], [0.6, 0.7], [1, 1]);
    const next = moveCurvePoint(curve, 1, 0.99, 1.4);

    expect(next[1]?.x).toBeCloseTo(0.59, 6);
    expect(next[1]?.y).toBe(1);
  });

  it("locks the endpoints to x=0 and x=1", () => {
    const curve = points([0, 0], [0.5, 0.5], [1, 1]);
    const first = moveCurvePoint(curve, 0, 0.3, 0.2);
    const last = moveCurvePoint(curve, 2, 0.7, 0.9);

    expect(first[0]).toEqual({ x: 0, y: 0.2 });
    expect(last[2]).toEqual({ x: 1, y: 0.9 });
  });

  it("does not delete endpoints and removes internal nodes", () => {
    const curve = points([0, 0], [0.4, 0.6], [0.7, 0.8], [1, 1]);

    expect(deleteCurvePoint(curve, 0)).toEqual(curve);
    expect(deleteCurvePoint(curve, 3)).toEqual(curve);
    expect(deleteCurvePoint(curve, 1)).toEqual(points([0, 0], [0.7, 0.8], [1, 1]));
  });

  it("does not mutate the input arrays", () => {
    const curve = points([0, 0], [0.5, 0.5], [1, 1]);
    const snapshot = JSON.stringify(curve);

    insertCurvePoint(curve, 0.2, 0.3);
    moveCurvePoint(curve, 1, 0.1, 0.9);
    deleteCurvePoint(curve, 1);

    expect(JSON.stringify(curve)).toBe(snapshot);
  });
});
