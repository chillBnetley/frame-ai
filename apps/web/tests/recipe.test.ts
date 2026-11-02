import { describe, expect, it } from "vitest";

import {
  DEFAULT_RECIPE,
  isDefaultRecipe,
  normalizeAdjustments,
  normalizeCrop,
  recipeFingerprint,
  roundTo2,
  withAdjustment,
} from "@/lib/recipe";

describe("roundTo2", () => {
  it.each([
    [0.1 + 0.2, 0.3],
    [1.234, 1.23],
    [1.236, 1.24],
    [1.005, 1],
    [12.3456, 12.35],
    [-0, 0],
  ])("normalizes %s to %s", (input, expected) => {
    expect(roundTo2(input)).toBe(expected);
  });

  it("never returns negative zero", () => {
    expect(Object.is(roundTo2(-0), -0)).toBe(false);
  });

  it("falls back to zero for non-finite input", () => {
    expect(roundTo2(Number.NaN)).toBe(0);
    expect(roundTo2(Number.POSITIVE_INFINITY)).toBe(0);
  });
});

describe("adjustment normalization", () => {
  it("fills defaults and clamps every numeric control", () => {
    const adjustments = normalizeAdjustments({
      exposureEv: 9,
      contrast: -140,
      sharpen: -5,
      rotationDeg: 22,
    });

    expect(adjustments.exposureEv).toBe(3);
    expect(adjustments.contrast).toBe(-100);
    expect(adjustments.sharpen).toBe(0);
    expect(adjustments.rotationDeg).toBe(15);
    expect(adjustments.tint).toBe(0);
    expect(adjustments.crop).toBeNull();
  });

  it("rounds numeric values to two decimals", () => {
    const adjustments = normalizeAdjustments({ exposureEv: 0.125, contrast: 12.3456 });

    expect(adjustments.exposureEv).toBe(0.13);
    expect(adjustments.contrast).toBe(12.35);
  });

  it("keeps crop inside the frame", () => {
    expect(normalizeCrop({ x: 0.8, y: 0.5, w: 0.5, h: 0.4 })).toEqual({
      x: 0.8,
      y: 0.5,
      w: 0.2,
      h: 0.4,
    });
    expect(normalizeCrop({ x: 1.2, y: 1.4, w: 1, h: 1 })).toEqual({
      x: 0.99,
      y: 0.99,
      w: 0.01,
      h: 0.01,
    });
    expect(normalizeCrop({ x: 0, y: 0, w: 1, h: 1 })).toBeNull();
  });

  it("returns a normalized copy when adjusting a single value", () => {
    const adjusted = withAdjustment(DEFAULT_RECIPE, "contrast", 20.126);

    expect(adjusted.adjustments.contrast).toBe(20.13);
    expect(adjusted.adjustments.exposureEv).toBe(0);
    expect(DEFAULT_RECIPE.adjustments.contrast).toBe(0);
  });
});

describe("recipe fingerprints", () => {
  it("ignores property insertion order", () => {
    const left = { ...DEFAULT_RECIPE, adjustments: { ...DEFAULT_RECIPE.adjustments } };
    const right = {
      warnings: [],
      rationale: [],
      adjustments: { ...DEFAULT_RECIPE.adjustments },
      styleStrength: 0,
      styleId: "natural" as const,
      schemaVersion: "1.0" as const,
    };

    expect(recipeFingerprint(left)).toBe(recipeFingerprint(right));
  });

  it("changes when an adjustment changes and recognizes the default", () => {
    const adjusted = withAdjustment(DEFAULT_RECIPE, "temperature", 5);

    expect(isDefaultRecipe(DEFAULT_RECIPE)).toBe(true);
    expect(isDefaultRecipe(adjusted)).toBe(false);
    expect(recipeFingerprint(adjusted)).not.toBe(recipeFingerprint(DEFAULT_RECIPE));
  });

  it("treats a full-frame crop the same as no crop", () => {
    const cropped = {
      ...DEFAULT_RECIPE,
      adjustments: {
        ...DEFAULT_RECIPE.adjustments,
        crop: { x: 0, y: 0, w: 1, h: 1 },
      },
    };

    expect(recipeFingerprint(cropped)).toBe(recipeFingerprint(DEFAULT_RECIPE));
  });
});
