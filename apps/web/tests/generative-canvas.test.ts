import { describe, expect, it } from "vitest";

import {
  CANVAS_ZOOM_STEP,
  MAX_CANVAS_SCALE,
  MIN_CANVAS_SCALE,
  clampScale,
  computeOutpaintGeometry,
  fitCanvasView,
  outpaintOverlayRect,
  panCanvasView,
  parseAspectRatio,
  zoomCanvasView,
} from "@/lib/generative-canvas";

const MARGINS = { top: 0, bottom: 0, left: 0, right: 0 };

describe("parseAspectRatio", () => {
  it("reads width:height pairs", () => {
    expect(parseAspectRatio("16:9")).toEqual({ width: 16, height: 9 });
  });

  it("rejects missing or malformed ratios", () => {
    expect(parseAspectRatio(null)).toBeNull();
    expect(parseAspectRatio("16")).toBeNull();
    expect(parseAspectRatio("0:9")).toBeNull();
    expect(parseAspectRatio("-4:3")).toBeNull();
    expect(parseAspectRatio("a:b")).toBeNull();
  });
});

describe("computeOutpaintGeometry", () => {
  it("keeps the requested margins when no ratio is set", () => {
    const geometry = computeOutpaintGeometry({
      baseWidth: 800,
      baseHeight: 600,
      margins: { top: 100, bottom: 50, left: 0, right: 200 },
      aspectRatio: null,
      alignment: "center",
    });

    expect(geometry).toEqual({
      top: 100,
      bottom: 50,
      left: 0,
      right: 200,
      targetWidth: 1000,
      targetHeight: 750,
      isExpanded: true,
    });
  });

  it("expands the shorter axis and splits the extra pixels for centring", () => {
    const geometry = computeOutpaintGeometry({
      baseWidth: 800,
      baseHeight: 600,
      margins: MARGINS,
      aspectRatio: "16:9",
      alignment: "center",
    });

    expect(geometry.targetWidth).toBe(1067);
    expect(geometry.targetHeight).toBe(600);
    expect(geometry.left).toBe(133);
    expect(geometry.right).toBe(134);
    expect(geometry.top).toBe(0);
    expect(geometry.bottom).toBe(0);
  });

  it("puts every extra pixel on the opposite side of the alignment", () => {
    const left = computeOutpaintGeometry({
      baseWidth: 800,
      baseHeight: 600,
      margins: MARGINS,
      aspectRatio: "16:9",
      alignment: "left",
    });
    expect(left).toMatchObject({ left: 0, right: 267, targetWidth: 1067 });

    const top = computeOutpaintGeometry({
      baseWidth: 1000,
      baseHeight: 1000,
      margins: MARGINS,
      aspectRatio: "9:16",
      alignment: "top",
    });
    expect(top).toMatchObject({ top: 0, bottom: 778, targetHeight: 1778 });
  });

  it("reports an unchanged frame when the ratio already matches", () => {
    const geometry = computeOutpaintGeometry({
      baseWidth: 800,
      baseHeight: 600,
      margins: MARGINS,
      aspectRatio: "4:3",
      alignment: "center",
    });

    expect(geometry).toMatchObject({ targetWidth: 800, targetHeight: 600, isExpanded: false });
  });

  it("applies manual margins before resolving the ratio", () => {
    const geometry = computeOutpaintGeometry({
      baseWidth: 800,
      baseHeight: 600,
      margins: { top: 0, bottom: 0, left: 200, right: 0 },
      aspectRatio: "1:1",
      alignment: "center",
    });

    expect(geometry).toMatchObject({
      left: 200,
      right: 0,
      top: 200,
      bottom: 200,
      targetWidth: 1000,
      targetHeight: 1000,
      isExpanded: true,
    });
  });
});

describe("clampScale", () => {
  it("keeps the scale inside the canvas limits", () => {
    expect(clampScale(0.01)).toBe(MIN_CANVAS_SCALE);
    expect(clampScale(100)).toBe(MAX_CANVAS_SCALE);
    expect(clampScale(1.5)).toBe(1.5);
  });

  it("falls back to 1 for unusable values", () => {
    expect(clampScale(Number.NaN)).toBe(1);
    expect(clampScale(Number.POSITIVE_INFINITY)).toBe(1);
  });
});

describe("fitCanvasView", () => {
  it("scales to the limiting axis minus the padding", () => {
    expect(fitCanvasView(200, 200, 400, 200, 10)).toEqual({
      scale: 0.45,
      offsetX: 0,
      offsetY: 0,
    });
  });

  it("fits a full-resolution portrait photo into the canvas well", () => {
    const view = fitCanvasView(550, 522, 3072, 4096);

    expect(view.scale).toBeCloseTo(522 / 4096, 6);
    expect(3072 * view.scale).toBeLessThanOrEqual(550);
    expect(4096 * view.scale).toBeLessThanOrEqual(522);
  });

  it("returns an identity view when either size is not usable", () => {
    expect(fitCanvasView(0, 200, 400, 200)).toEqual({ scale: 1, offsetX: 0, offsetY: 0 });
    expect(fitCanvasView(200, 200, 400, 0)).toEqual({ scale: 1, offsetX: 0, offsetY: 0 });
  });
});

describe("zoomCanvasView", () => {
  it("keeps the point under the pointer stationary", () => {
    const next = zoomCanvasView({ scale: 1, offsetX: 0, offsetY: 0 }, 2, 100, 50);

    expect(next).toEqual({ scale: 2, offsetX: -100, offsetY: -50 });
  });

  it("composes with an existing offset", () => {
    const next = zoomCanvasView({ scale: 2, offsetX: -40, offsetY: 20 }, 1.5, 10, 0);

    expect(next.scale).toBe(3);
    expect(next.offsetX).toBeCloseTo(1.5 * -40 + (1 - 1.5) * 10, 6);
    expect(next.offsetY).toBeCloseTo(1.5 * 20, 6);
  });

  it("returns the same view once the limit is reached", () => {
    const maxed = { scale: MAX_CANVAS_SCALE, offsetX: 5, offsetY: 7 };
    expect(zoomCanvasView(maxed, CANVAS_ZOOM_STEP, 0, 0)).toBe(maxed);
  });
});

describe("panCanvasView", () => {
  it("translates the view without touching the scale", () => {
    expect(panCanvasView({ scale: 1.5, offsetX: 10, offsetY: -20 }, 48, -12)).toEqual({
      scale: 1.5,
      offsetX: 58,
      offsetY: -32,
    });
  });
});

describe("outpaintOverlayRect", () => {
  it("places the source frame inside the expanded frame", () => {
    const geometry = computeOutpaintGeometry({
      baseWidth: 800,
      baseHeight: 600,
      margins: MARGINS,
      aspectRatio: "16:9",
      alignment: "center",
    });
    const rect = outpaintOverlayRect(800, 600, geometry);

    expect(rect.left).toBeCloseTo((133 / 1067) * 100, 6);
    expect(rect.top).toBe(0);
    expect(rect.width).toBeCloseTo((800 / 1067) * 100, 6);
    expect(rect.height).toBeCloseTo(100, 6);
  });

  it("covers the whole frame when nothing was expanded", () => {
    const geometry = computeOutpaintGeometry({
      baseWidth: 800,
      baseHeight: 600,
      margins: MARGINS,
      aspectRatio: null,
      alignment: "center",
    });

    expect(outpaintOverlayRect(800, 600, geometry)).toEqual({
      left: 0,
      top: 0,
      width: 100,
      height: 100,
    });
  });
});
