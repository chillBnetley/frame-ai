import { describe, expect, it } from "vitest";

import {
  applyTransform,
  cropBounds,
  displayRectToSourceRegion,
  displayToSourcePoint,
  ellipseOutline,
  inscribedScale,
  invertTransform,
  maskInnerOutlinePoints,
  maskOutlinePoints,
  outlineOverlapsDisplay,
  previewMaskGeometry,
  rectangleOutline,
  rotationMatrix,
  rotationTargetSize,
  sourceToDisplayTransform,
  svgMatrix,
} from "@/lib/mask-geometry";
import type { UserMask } from "@/types/session";

const SOURCE = { width: 200, height: 120 };
const CROP = { x: 0.1, y: 0.08, w: 0.72, h: 0.78 };

describe("rotation geometry", () => {
  it("inscribes the rotated canvas", () => {
    expect(inscribedScale(200, 120, 0)).toBe(1);
    expect(inscribedScale(120, 120, 90)).toBeCloseTo(1, 10);
    expect(inscribedScale(200, 120, 7.5)).toBeLessThan(1);
    expect(rotationTargetSize(SOURCE, 0)).toEqual({ width: 200, height: 120 });
    expect(rotationTargetSize(SOURCE, 7.5)).toEqual({ width: 165, height: 99 });
  });

  it("maps source pixels to the rotated target like OpenCV", () => {
    const target = { width: 101, height: 101 };
    const matrix = rotationMatrix({ width: 101, height: 101 }, 90, target);

    expect(matrix.a).toBeCloseTo(0, 10);
    expect(matrix.b).toBeCloseTo(-1, 10);
    expect(matrix.d).toBeCloseTo(1, 10);
    expect(matrix.e).toBeCloseTo(0, 10);
    const topLeft = applyTransform(matrix, { x: 0, y: 0 });
    const bottomRight = applyTransform(matrix, { x: 100, y: 100 });
    expect(topLeft.x).toBeCloseTo(100, 8);
    expect(topLeft.y).toBeCloseTo(0, 8);
    expect(bottomRight.x).toBeCloseTo(0, 8);
    expect(bottomRight.y).toBeCloseTo(100, 8);
  });

  it("bounds crops against the rotated canvas", () => {
    expect(cropBounds(null, { width: 165, height: 99 })).toEqual({
      x0: 0,
      y0: 0,
      x1: 165,
      y1: 99,
    });
    expect(cropBounds(CROP, { width: 165, height: 99 })).toEqual({
      x0: 16,
      y0: 8,
      x1: 135,
      y1: 85,
    });
  });
});

describe("source to display mapping", () => {
  it("is the identity without rotation or crop", () => {
    const transform = sourceToDisplayTransform(SOURCE, 0, null, SOURCE);

    expect(applyTransform(transform, { x: 0, y: 0 })).toEqual({ x: 0, y: 0 });
    expect(applyTransform(transform, { x: 0.5, y: 0.25 })).toEqual({ x: 0.5, y: 0.25 });
    expect(applyTransform(transform, { x: 1, y: 1 })).toEqual({ x: 1, y: 1 });
  });

  it("matches the backend transform for rotation plus crop", () => {
    const output = { width: 119, height: 77 };
    const transform = sourceToDisplayTransform(SOURCE, 7.5, CROP, output);

    expect(transform.a).toBeCloseTo(1.6662938847, 8);
    expect(transform.b).toBeCloseTo(-0.131623051, 8);
    expect(transform.c).toBeCloseTo(-0.2090962628, 8);
    expect(transform.d).toBeCloseTo(0.3390290707, 8);
    expect(transform.e).toBeCloseTo(1.5451088749, 8);
    expect(transform.f).toBeCloseTo(-0.402315914, 8);
    const matrixValues = svgMatrix(transform)
      .replace(/^matrix\(|\)$/g, "")
      .split(" ")
      .map(Number);
    expect(matrixValues).toHaveLength(6);
    expect(matrixValues[0]).toBeCloseTo(transform.a, 8);
    expect(matrixValues[1]).toBeCloseTo(transform.d, 8);
    expect(matrixValues[2]).toBeCloseTo(transform.b, 8);
    expect(matrixValues[3]).toBeCloseTo(transform.e, 8);
    expect(matrixValues[4]).toBeCloseTo(transform.c, 8);
    expect(matrixValues[5]).toBeCloseTo(transform.f, 8);
  });

  it("inverts the transform for pointer input", () => {
    const output = { width: 119, height: 77 };
    const transform = sourceToDisplayTransform(SOURCE, 7.5, CROP, output);
    const inverse = invertTransform(transform);

    expect(inverse).not.toBeNull();
    const source = displayToSourcePoint(transform, { x: 0.4, y: 0.6 });
    expect(source).not.toBeNull();
    const display = applyTransform(transform, source!);
    expect(display.x).toBeCloseTo(0.4, 10);
    expect(display.y).toBeCloseTo(0.6, 10);
  });

  it("rejects output sizes that do not match the crop", () => {
    expect(() =>
      sourceToDisplayTransform(SOURCE, 7.5, CROP, { width: 118, height: 77 }),
    ).toThrow("mask geometry does not match the output dimensions");
  });
});

describe("preview mask geometry", () => {
  it("uses the source dimensions when they are known", () => {
    const geometry = previewMaskGeometry(SOURCE, 7.5, CROP, SOURCE);

    expect(geometry).not.toBeNull();
    expect(geometry!.output).toEqual({ width: 119, height: 77 });
    expect(geometry!.transform.a).toBeCloseTo(1.6662938847, 8);
    expect(geometry!.transform.f).toBeCloseTo(-0.402315914, 8);
  });

  it("recovers an equivalent aspect when restored sessions lack source dimensions", () => {
    const preview = { width: 119, height: 77 };
    const geometry = previewMaskGeometry(preview, 7.5, CROP, null);

    expect(geometry).not.toBeNull();
    expect(geometry!.output.width / geometry!.output.height).toBeCloseTo(
      preview.width / preview.height,
      2,
    );
    const source = displayToSourcePoint(geometry!.transform, { x: 0.5, y: 0.5 });
    expect(source).not.toBeNull();
    const display = applyTransform(geometry!.transform, source!);
    expect(display.x).toBeCloseTo(0.5, 10);
    expect(display.y).toBeCloseTo(0.5, 10);
  });

  it("returns null without any dimensions", () => {
    expect(
      previewMaskGeometry({ width: 0, height: 0 }, 0, null, null),
    ).toBeNull();
  });
});

const MASK: UserMask = {
  id: "mask_1",
  shape: "rectangle",
  source: "user",
  coordinateSpace: "source-normalized",
  x: 0.2,
  y: 0.25,
  width: 0.4,
  height: 0.3,
  feather: 20,
  opacity: 100,
  inverted: false,
};

describe("mask outlines", () => {
  it("builds four rectangle corners and a sampled ellipse", () => {
    const rectangle = rectangleOutline(MASK);
    expect(rectangle).toHaveLength(4);
    expect(rectangle[0]!.x).toBeCloseTo(0.2, 10);
    expect(rectangle[0]!.y).toBeCloseTo(0.25, 10);
    expect(rectangle[2]!.x).toBeCloseTo(0.6, 10);
    expect(rectangle[2]!.y).toBeCloseTo(0.55, 10);
    expect(ellipseOutline(MASK)).toHaveLength(64);
    const geometry = previewMaskGeometry(SOURCE, 0, null, SOURCE)!;
    const outline = maskOutlinePoints({ ...MASK, shape: "ellipse" }, geometry.transform);
    expect(outline).toHaveLength(64);
    expect(outline[0]?.x).toBeCloseTo(0.6, 10);
    expect(outline[0]?.y).toBeCloseTo(0.4, 10);
  });

  it("insets the feather band inside the shape", () => {
    const geometry = previewMaskGeometry(SOURCE, 0, null, SOURCE)!;
    expect(
      maskInnerOutlinePoints({ ...MASK, feather: 0 }, geometry.transform),
    ).toEqual([]);
    const inner = maskInnerOutlinePoints(MASK, geometry.transform);
    expect(inner).toHaveLength(4);
    expect(inner[0]?.x).toBeCloseTo(0.24, 10);
    expect(inner[0]?.y).toBeCloseTo(0.28, 10);
    expect(inner[2]?.x).toBeCloseTo(0.56, 10);
    expect(inner[2]?.y).toBeCloseTo(0.52, 10);
  });

  it("inverts drag corners into a clamped source region", () => {
    const geometry = previewMaskGeometry(SOURCE, 7.5, CROP, SOURCE)!;
    const region = displayRectToSourceRegion(
      geometry.transform,
      { x: 0.3, y: 0.3 },
      { x: 0.7, y: 0.8 },
    );

    expect(region).not.toBeNull();
    expect(region!.x).toBeGreaterThanOrEqual(0);
    expect(region!.y).toBeGreaterThanOrEqual(0);
    expect(region!.x + region!.width).toBeLessThanOrEqual(1);
    expect(region!.y + region!.height).toBeLessThanOrEqual(1);
    expect(region!.width).toBeGreaterThan(0);
    expect(region!.height).toBeGreaterThan(0);
  });

  it("detects whether an outline overlaps the visible frame", () => {
    expect(
      outlineOverlapsDisplay([
        { x: 0.2, y: 0.2 },
        { x: 0.4, y: 0.4 },
      ]),
    ).toBe(true);
    expect(
      outlineOverlapsDisplay([
        { x: 1.2, y: 0.2 },
        { x: 1.4, y: 0.4 },
      ]),
    ).toBe(false);
  });
});
