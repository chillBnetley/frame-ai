import { describe, expect, it } from "vitest";

import {
  DEFAULT_RECIPE,
  addLocalAdjustment,
  addMask,
  createMask,
  createMaskId,
  isDefaultRecipe,
  moveLocalAdjustment,
  normalizeAdjustments,
  normalizeColorGrading,
  normalizeCrop,
  normalizeCurveChannel,
  normalizeCurveSet,
  normalizeHsl,
  normalizeLocalAdjustmentValues,
  normalizeLocalAdjustments,
  normalizeMask,
  normalizeMasks,
  normalizeOutput,
  normalizeRecipe,
  recipeFingerprint,
  removeLocalAdjustment,
  removeMask,
  resetLocalAdjustment,
  roundTo2,
  roundTo4,
  roundTo6,
  setLocalAdjustmentEnabled,
  setLocalAdjustmentBlendMode,
  setLocalAdjustmentMask,
  setLocalAdjustmentOpacity,
  updateLocalAdjustment,
  updateMask,
  withAdjustment,
  withColorGradeZone,
  withColorGradingSet,
  withCurve,
  withCurveSet,
  withHsl,
  withHslSet,
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

    expect(adjustments.exposureEv).toBe(5);
    expect(adjustments.contrast).toBe(-100);
    expect(adjustments.sharpen).toBe(0);
    expect(adjustments.rotationDeg).toBe(15);
    expect(adjustments.tint).toBe(0);
    expect(adjustments.whites).toBe(0);
    expect(adjustments.blacks).toBe(0);
    expect(adjustments.crop).toBeNull();
  });

  it("rounds numeric values to two decimals", () => {
    const adjustments = normalizeAdjustments({ exposureEv: 0.125, contrast: 12.3456 });

    expect(adjustments.exposureEv).toBe(0.13);
    expect(adjustments.contrast).toBe(12.35);
  });

  it("rounds curve values to six decimals", () => {
    expect(roundTo6(0.1234567)).toBe(0.123457);
    expect(roundTo6(-0)).toBe(0);
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

  it("supports whites and blacks within the shared range", () => {
    expect(normalizeAdjustments({ whites: 140, blacks: -140 })).toMatchObject({
      whites: 100,
      blacks: -100,
    });
    expect(withAdjustment(DEFAULT_RECIPE, "whites", 12.345).adjustments.whites).toBe(12.35);
  });
});

describe("recipe schema 2.0 groups", () => {
  it("fills a complete default recipe", () => {
    const recipe = normalizeRecipe({});

    expect(recipe.schemaVersion).toBe("2.0");
    expect(recipe.curve).toEqual({ master: [], red: [], green: [], blue: [] });
    expect(recipe.hsl.red).toEqual({ hue: 0, saturation: 0, luminance: 0 });
    expect(recipe.colorGrading).toEqual({
      shadows: { hue: 0, saturation: 0 },
      midtones: { hue: 0, saturation: 0 },
      highlights: { hue: 0, saturation: 0 },
      balance: 0,
      blending: 50,
    });
    expect(recipe.localAdjustments).toEqual([]);
    expect(recipe.output).toEqual({ format: "jpeg", quality: 92, colorSpace: "sRGB" });
    expect(recipe.adjustments.whites).toBe(0);
    expect(recipe.adjustments.blacks).toBe(0);
  });

  it("orders, deduplicates and clamps curve points", () => {
    const points = normalizeCurveChannel([
      { x: 0.5, y: 1.4 },
      { x: 0.25, y: -0.2 },
      { x: 0.5, y: 0.8 },
      { x: Number.NaN, y: 0.4 },
    ]);

    expect(points).toEqual([
      { x: 0.25, y: 0 },
      { x: 0.5, y: 1 },
    ]);
    expect(normalizeCurveChannel([{ x: 0.2, y: 0.2 }])).toEqual([]);
    expect(normalizeCurveSet(undefined)).toEqual({
      master: [],
      red: [],
      green: [],
      blue: [],
    });
  });

  it("caps curves at 32 points", () => {
    const points = Array.from({ length: 40 }, (_, index) => ({
      x: index / 40,
      y: index / 40,
    }));

    expect(normalizeCurveChannel(points)).toHaveLength(32);
  });

  it("clamps HSL and color grading values", () => {
    const hsl = normalizeHsl({
      red: { hue: 270, saturation: -140, luminance: 140 },
    });
    expect(hsl.red).toEqual({ hue: 180, saturation: -100, luminance: 100 });
    expect(hsl.blue).toEqual({ hue: 0, saturation: 0, luminance: 0 });

    const grading = normalizeColorGrading({
      shadows: { hue: 400, saturation: 130 },
      balance: -180,
      blending: 130,
    });
    expect(grading.shadows).toEqual({ hue: 360, saturation: 100 });
    expect(grading.balance).toBe(-100);
    expect(grading.blending).toBe(100);
  });

  it("drops invalid local adjustments, sorts by id and caps the count", () => {
    const items = normalizeLocalAdjustments([
      { id: "local_b", maskId: "mask_face", enabled: false, adjustments: { exposureEv: 0.5 } },
      { id: "bad", maskId: "full" },
      { id: "local_a", maskId: "full", adjustments: { contrast: 200 } },
      { id: "local_b", maskId: "full" },
      { id: "local_c", maskId: "face" },
    ]);

    expect(items.map((item) => item.id)).toEqual(["local_a", "local_b"]);
    expect(items[0]?.adjustments?.contrast).toBe(100);
    expect(items[1]).toMatchObject({ maskId: "mask_face", enabled: false });
  });

  it("limits local adjustments to 20 sorted ids", () => {
    const items = Array.from({ length: 25 }, (_, index) => ({
      id: `local_${String(index).padStart(3, "0")}`,
      maskId: "full",
    }));

    const normalized = normalizeLocalAdjustments(items);
    expect(normalized).toHaveLength(20);
    expect(normalized[0]?.id).toBe("local_000");
    expect(normalized[19]?.id).toBe("local_019");
  });

  it("preserves layer fields and sorts by order", () => {
    const items = normalizeLocalAdjustments([
      {
        id: "local_b",
        maskId: "full",
        enabled: true,
        name: "Second",
        blendMode: "screen",
        opacity: 35,
        order: 1,
      },
      {
        id: "local_a",
        maskId: "full",
        enabled: false,
        name: null,
        blendMode: "normal",
        opacity: 100,
        order: 0,
      },
    ]);

    expect(items.map((item) => item.id)).toEqual(["local_a", "local_b"]);
    expect(items[1]).toMatchObject({
      name: "Second",
      blendMode: "screen",
      opacity: 35,
      order: 1,
    });
  });

  it("adds layers in order, moves them, and renumbers after removal", () => {
    const one = addLocalAdjustment(DEFAULT_RECIPE);
    const two = addLocalAdjustment(one);
    expect(two.localAdjustments.map((item) => item.order)).toEqual([0, 1]);

    const three = addLocalAdjustment(two);
    const secondId = three.localAdjustments[2]!.id;
    const moved = moveLocalAdjustment(three, secondId, -1);
    expect(moved.localAdjustments.map((item) => item.order)).toEqual([0, 1, 2]);
    expect(moved.localAdjustments[1]!.id).toBe(secondId);

    const removed = removeLocalAdjustment(moved, secondId);
    expect(removed.localAdjustments.map((item) => item.order)).toEqual([0, 1]);
    expect(removed.localAdjustments.map((item) => item.id)).not.toContain(secondId);
  });

  it("renumbers sparse orders before appending a new layer", () => {
    const sparse = normalizeRecipe({
      localAdjustments: [
        {
          id: "local_a",
          maskId: "full",
          enabled: true,
          name: null,
          blendMode: "normal",
          opacity: 100,
          order: 1,
          adjustments: normalizeLocalAdjustmentValues({ exposureEv: 0.2 }),
        },
        {
          id: "local_b",
          maskId: "full",
          enabled: true,
          name: null,
          blendMode: "normal",
          opacity: 100,
          order: 2,
          adjustments: normalizeLocalAdjustmentValues({ contrast: 5 }),
        },
      ],
    });

    const added = addLocalAdjustment(sparse);

    expect(added.localAdjustments.map((item) => item.order)).toEqual([0, 1, 2]);
    expect(new Set(added.localAdjustments.map((item) => item.order)).size).toBe(3);
  });

  it("normalizes legacy all-zero orders before appending", () => {
    const legacy = normalizeRecipe({
      localAdjustments: [
        {
          id: "local_a",
          maskId: "full",
          enabled: true,
          name: null,
          blendMode: "normal",
          opacity: 100,
          order: 0,
          adjustments: normalizeLocalAdjustmentValues({ exposureEv: 0.2 }),
        },
        {
          id: "local_b",
          maskId: "full",
          enabled: true,
          name: null,
          blendMode: "normal",
          opacity: 100,
          order: 0,
          adjustments: normalizeLocalAdjustmentValues({ contrast: 5 }),
        },
      ],
    });

    const added = addLocalAdjustment(legacy);

    expect(added.localAdjustments.map((item) => item.order)).toEqual([0, 1, 2]);
  });

  it("updates blend mode and opacity with clamping", () => {
    const recipe = addLocalAdjustment(DEFAULT_RECIPE);
    const id = recipe.localAdjustments[0]!.id;

    const blended = setLocalAdjustmentBlendMode(recipe, id, "multiply");
    expect(blended.localAdjustments[0]!.blendMode).toBe("multiply");

    const faded = setLocalAdjustmentOpacity(blended, id, 150);
    expect(faded.localAdjustments[0]!.opacity).toBe(100);
    const transparent = setLocalAdjustmentOpacity(faded, id, -5);
    expect(transparent.localAdjustments[0]!.opacity).toBe(0);
  });

  it("keeps layer fields on the remaining rows after a deletion", () => {
    const first = addLocalAdjustment(DEFAULT_RECIPE);
    const second = addLocalAdjustment(first);
    const firstId = second.localAdjustments[0]!.id;
    const secondId = second.localAdjustments[1]!.id;
    const blended = setLocalAdjustmentBlendMode(second, firstId, "overlay");

    const removed = removeLocalAdjustment(blended, secondId);

    expect(removed.localAdjustments).toHaveLength(1);
    expect(removed.localAdjustments[0]).toMatchObject({
      id: firstId,
      blendMode: "overlay",
      order: 0,
    });
  });

  it("normalizes output settings", () => {
    expect(normalizeOutput({ format: "png", quality: 150.6 })).toEqual({
      format: "png",
      quality: 100,
      colorSpace: "sRGB",
    });
    expect(normalizeOutput({ quality: 0.4 })).toEqual({
      format: "jpeg",
      quality: 1,
      colorSpace: "sRGB",
    });
    expect(normalizeOutput(undefined)).toEqual({
      format: "jpeg",
      quality: 92,
      colorSpace: "sRGB",
    });
  });
});

describe("mask normalization", () => {
  it("rounds mask coordinates to four decimals and keeps them inside the frame", () => {
    const mask = normalizeMask({
      id: "mask_a",
      x: 0.8,
      y: 0.7,
      width: 0.5,
      height: 0.6,
      feather: 15,
    });

    expect(mask).toEqual({
      id: "mask_a",
      shape: "rectangle",
      source: "user",
      coordinateSpace: "source-normalized",
      x: 0.8,
      y: 0.7,
      width: 0.2,
      height: 0.3,
      feather: 15,
      opacity: 100,
      inverted: false,
    });
    expect(roundTo4(0.123456)).toBe(0.1235);
  });

  it("rejects invalid ids and falls back for invalid fields", () => {
    expect(normalizeMask({ id: "full", x: 0, y: 0, width: 1, height: 1 })).toBeNull();
    const mask = normalizeMask({
      id: "mask_b",
      x: Number.NaN,
      y: 1.5,
      width: Number.POSITIVE_INFINITY,
      height: 0,
      shape: "triangle" as never,
      feather: 250,
      opacity: -20,
    });

    expect(mask).toMatchObject({
      x: 0,
      y: 0.9999,
      width: 1,
      height: 0.0001,
      shape: "rectangle",
      feather: 100,
      opacity: 0,
    });
  });

  it("deduplicates, sorts and caps masks", () => {
    const masks = normalizeMasks([
      { id: "mask_b", x: 0, y: 0, width: 0.5, height: 0.5 },
      { id: "mask_a", shape: "ellipse", x: 0.2, y: 0.2, width: 0.4, height: 0.4 },
      { id: "mask_b", x: 0.4, y: 0.4, width: 0.2, height: 0.2 },
      { id: "bad", x: 0, y: 0, width: 1, height: 1 },
      ...Array.from({ length: 25 }, (_, index) => ({
        id: `mask_z${index}`,
        x: 0,
        y: 0,
        width: 1,
        height: 1,
      })),
    ]);

    expect(masks[0]?.id).toBe("mask_a");
    expect(masks[0]?.shape).toBe("ellipse");
    expect(masks).toHaveLength(20);
    expect(masks.filter((mask) => mask.id === "mask_b")).toHaveLength(1);
    expect(masks.some((mask) => mask.id === "bad")).toBe(false);
  });

  it("generates the next free mask id", () => {
    const masks = [createMask("mask_1"), createMask("mask_2")];
    expect(createMaskId(masks)).toBe("mask_3");
  });
});

describe("mask and local adjustment mutations", () => {
  it("adds, updates and removes masks without mutating the input", () => {
    const added = addMask(DEFAULT_RECIPE, createMask("mask_1"));
    expect(added.masks).toHaveLength(1);
    expect(DEFAULT_RECIPE.masks).toEqual([]);
    expect(recipeFingerprint(added)).not.toBe(recipeFingerprint(DEFAULT_RECIPE));

    const updated = updateMask(added, "mask_1", {
      shape: "ellipse",
      feather: 250,
      opacity: -5,
      inverted: true,
    });
    expect(updated.masks[0]).toMatchObject({
      shape: "ellipse",
      feather: 100,
      opacity: 0,
      inverted: true,
    });

    expect(removeMask(updated, "mask_1").masks).toEqual([]);
    expect(isDefaultRecipe(removeMask(updated, "mask_1"))).toBe(true);
  });

  it("removes the local adjustments that pointed at a deleted mask", () => {
    let recipe = addMask(DEFAULT_RECIPE, createMask("mask_1"));
    recipe = addMask(recipe, createMask("mask_2"));
    recipe = addLocalAdjustment(recipe, "mask_1", { exposureEv: 1 });
    recipe = addLocalAdjustment(recipe, "mask_2", { exposureEv: -1 });

    const removed = removeMask(recipe, "mask_1");

    expect(removed.masks.map((mask) => mask.id)).toEqual(["mask_2"]);
    expect(removed.localAdjustments.map((item) => item.maskId)).toEqual(["mask_2"]);
  });

  it("keeps full-canvas adjustments when a mask is removed", () => {
    let recipe = addMask(DEFAULT_RECIPE, createMask("mask_1"));
    recipe = addLocalAdjustment(recipe, "full", { exposureEv: 0.5 });

    const removed = removeMask(recipe, "mask_1");

    expect(removed.masks).toEqual([]);
    expect(removed.localAdjustments).toHaveLength(1);
    expect(removed.localAdjustments[0]?.maskId).toBe("full");
  });

  it("is idempotent when the same mask is removed twice", () => {
    let recipe = addMask(DEFAULT_RECIPE, createMask("mask_1"));
    recipe = addLocalAdjustment(recipe, "mask_1", { exposureEv: 1 });

    const once = removeMask(recipe, "mask_1");
    const twice = removeMask(once, "mask_1");

    expect(twice).toEqual(once);
    expect(recipeFingerprint(twice)).toBe(recipeFingerprint(once));
  });

  it("adds and edits local adjustments with v1 fields only", () => {
    const withMask = addMask(DEFAULT_RECIPE, createMask("mask_1"));
    const added = addLocalAdjustment(withMask, "mask_1", {
      exposureEv: 2,
      contrast: 200,
      sharpen: 70,
      denoise: 70,
    });

    expect(added.localAdjustments).toHaveLength(1);
    const item = added.localAdjustments[0];
    expect(item.id).toBe("local_1");
    expect(item.maskId).toBe("mask_1");
    expect(item.adjustments).toMatchObject({
      exposureEv: 2,
      contrast: 100,
      sharpen: 0,
      denoise: 0,
      vignette: 0,
      grain: 0,
    });

    const edited = updateLocalAdjustment(added, "local_1", "exposureEv", 9);
    expect(edited.localAdjustments[0]?.adjustments?.exposureEv).toBe(5);

    const disabled = setLocalAdjustmentEnabled(edited, "local_1", false);
    expect(disabled.localAdjustments[0]?.enabled).toBe(false);

    const reassigned = setLocalAdjustmentMask(disabled, "local_1", "mask_missing");
    expect(reassigned.localAdjustments[0]?.maskId).toBe("mask_missing");
    expect(setLocalAdjustmentMask(disabled, "local_1", "nope").localAdjustments[0]?.maskId).toBe(
      "full",
    );
  });

  it("resets every supported local field and drops unsupported fields during normalization", () => {
    const added = addLocalAdjustment(DEFAULT_RECIPE, "full", {
      exposureEv: 1,
      clarity: 12,
      sharpen: 40,
    });
    expect(added.localAdjustments[0]?.adjustments).toMatchObject({
      exposureEv: 1,
      sharpen: 0,
      clarity: 12,
    });
    expect(resetLocalAdjustment(added, "local_1").localAdjustments[0]?.adjustments)
      .toMatchObject({ exposureEv: 0, clarity: 0, sharpen: 0, denoise: 0 });

    expect(removeLocalAdjustment(added, "local_1").localAdjustments).toEqual([]);

    const normalized = normalizeLocalAdjustments([
      {
        id: "local_a",
        maskId: "full",
        adjustments: { exposureEv: 1, grain: 50, vignette: 30 },
      },
    ]);
    expect(normalized[0]?.adjustments).toMatchObject({ exposureEv: 1, grain: 0, vignette: 0 });
  });

  it("prunes masks that no longer have a local adjustment", () => {
    let recipe = addMask(DEFAULT_RECIPE, createMask("mask_1"));
    recipe = addMask(recipe, createMask("mask_2"));
    recipe = addLocalAdjustment(recipe, "mask_1");
    recipe = addLocalAdjustment(recipe, "mask_2");
    expect(recipe.masks).toHaveLength(2);

    const removed = removeLocalAdjustment(recipe, "local_1");

    expect(removed.masks.map((mask) => mask.id)).toEqual(["mask_2"]);
    expect(removed.localAdjustments).toHaveLength(1);
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
      schemaVersion: "2.0" as const,
      masks: [],
      localAdjustments: [],
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

describe("curve recipe helpers", () => {
  it("normalizes curve points and keeps empty channels identical", () => {
    const recipe = withCurveSet(DEFAULT_RECIPE, {
      master: [
        { x: 0.8, y: 0.9 },
        { x: 0.2, y: 0.1234567 },
        { x: 0.2, y: 0.3 },
      ],
      red: [{ x: 0.5, y: 0.5 }],
    });

    expect(recipe.curve.master).toEqual([
      { x: 0.2, y: 0.123457 },
      { x: 0.8, y: 0.9 },
    ]);
    expect(recipe.curve.red).toEqual([]);
    expect(recipe.curve.green).toEqual([]);
  });

  it("changes the fingerprint only when the curve changes", () => {
    const shaped = withCurve(DEFAULT_RECIPE, "master", [
      { x: 0, y: 0 },
      { x: 0.5, y: 0.7 },
      { x: 1, y: 1 },
    ]);

    expect(recipeFingerprint(shaped)).not.toBe(recipeFingerprint(DEFAULT_RECIPE));
    expect(isDefaultRecipe(shaped)).toBe(false);
    expect(isDefaultRecipe(withCurveSet(DEFAULT_RECIPE, {}))).toBe(true);

    const channelOnly = withCurve(DEFAULT_RECIPE, "blue", [
      { x: 0, y: 0.1 },
      { x: 1, y: 1 },
    ]);
    expect(channelOnly.curve.blue).toHaveLength(2);
    expect(channelOnly.curve.master).toEqual([]);
    expect(recipeFingerprint(channelOnly)).not.toBe(recipeFingerprint(shaped));
  });
});

describe("HSL recipe mutations", () => {
  it("sets one band parameter and rounds it", () => {
    const recipe = withHsl(DEFAULT_RECIPE, "blue", "hue", 32.456);

    expect(recipe.hsl.blue).toEqual({ hue: 32.46, saturation: 0, luminance: 0 });
    expect(recipe.hsl.red).toEqual({ hue: 0, saturation: 0, luminance: 0 });
  });

  it("clamps band values to their ranges", () => {
    expect(withHsl(DEFAULT_RECIPE, "red", "hue", 999).hsl.red.hue).toBe(180);
    expect(withHsl(DEFAULT_RECIPE, "red", "hue", -999).hsl.red.hue).toBe(-180);
    expect(withHsl(DEFAULT_RECIPE, "green", "saturation", -140).hsl.green.saturation).toBe(-100);
    expect(withHsl(DEFAULT_RECIPE, "green", "luminance", 140).hsl.green.luminance).toBe(100);
  });

  it("replaces or clears the whole HSL set", () => {
    const recipe = withHslSet(DEFAULT_RECIPE, {
      orange: { hue: 12, saturation: 8, luminance: -4 },
    });

    expect(recipe.hsl.orange).toEqual({ hue: 12, saturation: 8, luminance: -4 });
    expect(isDefaultRecipe(recipe)).toBe(false);
    expect(isDefaultRecipe(withHslSet(recipe, {}))).toBe(true);
  });

  it("changes the fingerprint only when HSL changes", () => {
    const shaped = withHsl(DEFAULT_RECIPE, "aqua", "luminance", 15);

    expect(recipeFingerprint(shaped)).not.toBe(recipeFingerprint(DEFAULT_RECIPE));
    expect(recipeFingerprint(withHslSet(DEFAULT_RECIPE, {}))).toBe(
      recipeFingerprint(DEFAULT_RECIPE),
    );
  });
});

describe("color grading recipe mutations", () => {
  it("sets one zone parameter and rounds it", () => {
    const recipe = withColorGradeZone(DEFAULT_RECIPE, "shadows", "hue", 219.567);

    expect(recipe.colorGrading.shadows).toEqual({ hue: 219.57, saturation: 0 });
    expect(recipe.colorGrading.highlights).toEqual({ hue: 0, saturation: 0 });
  });

  it("clamps zone values to their ranges", () => {
    expect(
      withColorGradeZone(DEFAULT_RECIPE, "shadows", "hue", 999).colorGrading.shadows.hue,
    ).toBe(360);
    expect(
      withColorGradeZone(DEFAULT_RECIPE, "shadows", "hue", -5).colorGrading.shadows.hue,
    ).toBe(0);
    expect(
      withColorGradeZone(DEFAULT_RECIPE, "midtones", "saturation", 140).colorGrading
        .midtones.saturation,
    ).toBe(100);
  });

  it("replaces or clears the whole grading block", () => {
    const recipe = withColorGradingSet(DEFAULT_RECIPE, {
      shadows: { hue: 220, saturation: 30 },
      balance: 10,
      blending: 70,
    });

    expect(recipe.colorGrading.shadows).toEqual({ hue: 220, saturation: 30 });
    expect(recipe.colorGrading.balance).toBe(10);
    expect(recipe.colorGrading.blending).toBe(70);
    expect(isDefaultRecipe(recipe)).toBe(false);
    expect(isDefaultRecipe(withColorGradingSet(recipe, {}))).toBe(true);
  });

  it("changes the fingerprint only when grading changes", () => {
    const shaped = withColorGradeZone(DEFAULT_RECIPE, "highlights", "saturation", 25);

    expect(recipeFingerprint(shaped)).not.toBe(recipeFingerprint(DEFAULT_RECIPE));
    expect(recipeFingerprint(withColorGradingSet(DEFAULT_RECIPE, {}))).toBe(
      recipeFingerprint(DEFAULT_RECIPE),
    );
  });
});
