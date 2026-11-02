import type {
  Adjustments,
  Crop,
  EditRecipe,
  EditorRecipe,
} from "@/types/session";

export const NUMERIC_ADJUSTMENT_KEYS = [
  "exposureEv",
  "contrast",
  "highlights",
  "shadows",
  "temperature",
  "tint",
  "saturation",
  "vibrance",
  "clarity",
  "sharpen",
  "denoise",
  "vignette",
  "grain",
  "rotationDeg",
] as const;

export type NumericAdjustmentKey = (typeof NUMERIC_ADJUSTMENT_KEYS)[number];

export interface AdjustmentRange {
  min: number;
  max: number;
  step: number;
  defaultValue: number;
}

export const ADJUSTMENT_RANGES = {
  exposureEv: { min: -3, max: 3, step: 0.01, defaultValue: 0 },
  contrast: { min: -100, max: 100, step: 1, defaultValue: 0 },
  highlights: { min: -100, max: 100, step: 1, defaultValue: 0 },
  shadows: { min: -100, max: 100, step: 1, defaultValue: 0 },
  temperature: { min: -100, max: 100, step: 1, defaultValue: 0 },
  tint: { min: -100, max: 100, step: 1, defaultValue: 0 },
  saturation: { min: -100, max: 100, step: 1, defaultValue: 0 },
  vibrance: { min: -100, max: 100, step: 1, defaultValue: 0 },
  clarity: { min: -100, max: 100, step: 1, defaultValue: 0 },
  sharpen: { min: 0, max: 100, step: 1, defaultValue: 0 },
  denoise: { min: 0, max: 100, step: 1, defaultValue: 0 },
  vignette: { min: -100, max: 100, step: 1, defaultValue: 0 },
  grain: { min: 0, max: 100, step: 1, defaultValue: 0 },
  rotationDeg: { min: -15, max: 15, step: 0.01, defaultValue: 0 },
} as const satisfies Record<NumericAdjustmentKey, AdjustmentRange>;

export const DEFAULT_ADJUSTMENTS: Adjustments = {
  exposureEv: 0,
  contrast: 0,
  highlights: 0,
  shadows: 0,
  temperature: 0,
  tint: 0,
  saturation: 0,
  vibrance: 0,
  clarity: 0,
  sharpen: 0,
  denoise: 0,
  vignette: 0,
  grain: 0,
  rotationDeg: 0,
  crop: null,
};

export const DEFAULT_RECIPE: EditorRecipe = {
  schemaVersion: "1.0",
  styleId: "natural",
  styleStrength: 0,
  adjustments: { ...DEFAULT_ADJUSTMENTS },
  rationale: [],
  warnings: [],
};

export function roundTo2(value: number): number {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.round(value * 100) / 100 + 0;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function normalizeCrop(crop: Crop | null | undefined): Crop | null {
  if (!crop) {
    return null;
  }
  const x = roundTo2(clamp(crop.x, 0, 0.99));
  const y = roundTo2(clamp(crop.y, 0, 0.99));
  const w = roundTo2(clamp(crop.w, 0.01, 1));
  const h = roundTo2(clamp(crop.h, 0.01, 1));
  const boundedWidth = roundTo2(Math.min(w, Math.max(0.01, roundTo2(1 - x))));
  const boundedHeight = roundTo2(Math.min(h, Math.max(0.01, roundTo2(1 - y))));
  if (x === 0 && y === 0 && boundedWidth === 1 && boundedHeight === 1) {
    return null;
  }
  return { x, y, w: boundedWidth, h: boundedHeight };
}

export function normalizeAdjustments(
  adjustments: Partial<Adjustments> | undefined,
): Adjustments {
  const source = { ...DEFAULT_ADJUSTMENTS, ...(adjustments ?? {}) };
  const normalized = { ...DEFAULT_ADJUSTMENTS };
  for (const key of NUMERIC_ADJUSTMENT_KEYS) {
    const range = ADJUSTMENT_RANGES[key];
    const raw = source[key];
    const value = typeof raw === "number" && Number.isFinite(raw) ? raw : range.defaultValue;
    normalized[key] = roundTo2(clamp(value, range.min, range.max));
  }
  normalized.crop = normalizeCrop(source.crop);
  return normalized;
}

export function normalizeRecipe(recipe: EditRecipe): EditorRecipe {
  return {
    schemaVersion: "1.0",
    styleId: recipe.styleId ?? "natural",
    styleStrength: roundTo2(clamp(recipe.styleStrength ?? 0, 0, 100)),
    adjustments: normalizeAdjustments(recipe.adjustments),
    rationale: [...(recipe.rationale ?? [])].slice(0, 8),
    warnings: [...(recipe.warnings ?? [])].slice(0, 8),
  };
}

export function createDefaultRecipe(): EditorRecipe {
  return normalizeRecipe(DEFAULT_RECIPE);
}

export function withAdjustment(
  recipe: EditRecipe,
  key: NumericAdjustmentKey,
  value: number,
): EditorRecipe {
  const range = ADJUSTMENT_RANGES[key];
  return normalizeRecipe({
    ...recipe,
    adjustments: {
      ...normalizeAdjustments(recipe.adjustments),
      [key]: roundTo2(clamp(value, range.min, range.max)),
    },
  });
}

export function withCrop(recipe: EditRecipe, crop: Crop | null): EditorRecipe {
  return normalizeRecipe({
    ...recipe,
    adjustments: {
      ...normalizeAdjustments(recipe.adjustments),
      crop: normalizeCrop(crop),
    },
  });
}

function stableStringify(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(stableStringify).join(",")}]`;
  }
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, entry]) => entry !== undefined)
      .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
      .map(([key, entry]) => `${JSON.stringify(key)}:${stableStringify(entry)}`);
    return `{${entries.join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

export function recipeFingerprint(recipe: EditRecipe): string {
  return stableStringify(normalizeRecipe(recipe));
}

export const DEFAULT_RECIPE_FINGERPRINT = recipeFingerprint(DEFAULT_RECIPE);

export function isDefaultRecipe(recipe: EditRecipe): boolean {
  return recipeFingerprint(recipe) === DEFAULT_RECIPE_FINGERPRINT;
}
