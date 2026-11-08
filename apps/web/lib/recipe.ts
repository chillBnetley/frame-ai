import type {
  Adjustments,
  ColorGradeZone,
  ColorGradeZoneName,
  ColorGrading,
  Crop,
  CurvePoint,
  CurveSet,
  EditRecipe,
  EditorRecipe,
  HslAdjustments,
  HslBand,
  LocalAdjustment,
  LocalAdjustments,
  MaskShape,
  OutputSettings,
  UserMask,
} from "@/types/session";

export const NUMERIC_ADJUSTMENT_KEYS = [
  "exposureEv",
  "contrast",
  "highlights",
  "shadows",
  "whites",
  "blacks",
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

export const LOCAL_ADJUSTMENT_KEYS = [
  "exposureEv",
  "contrast",
  "highlights",
  "shadows",
  "whites",
  "blacks",
  "temperature",
  "tint",
  "saturation",
  "vibrance",
  "clarity",
  "sharpen",
  "denoise",
  "vignette",
  "grain",
] as const satisfies readonly NumericAdjustmentKey[];

export type LocalAdjustmentKey = (typeof LOCAL_ADJUSTMENT_KEYS)[number];

export const LOCAL_V1_ADJUSTMENT_KEYS = [
  "exposureEv",
  "contrast",
  "highlights",
  "shadows",
  "whites",
  "blacks",
  "temperature",
  "tint",
  "saturation",
  "vibrance",
  "clarity",
] as const satisfies readonly LocalAdjustmentKey[];

export type LocalV1AdjustmentKey = (typeof LOCAL_V1_ADJUSTMENT_KEYS)[number];

export const STYLE_IDS = [
  "natural",
  "portrait",
  "landscape",
  "street",
  "documentary",
  "film",
  "cinematic",
] as const;

export const CURVE_CHANNELS = ["master", "red", "green", "blue"] as const;
export const CURVE_MAX_POINTS = 32;

export const HSL_BAND_NAMES = [
  "red",
  "orange",
  "yellow",
  "green",
  "aqua",
  "blue",
  "purple",
  "magenta",
] as const;

export const COLOR_GRADE_ZONE_NAMES = ["shadows", "midtones", "highlights"] as const;

export const LOCAL_ADJUSTMENT_LIMIT = 20;
export const LAYER_UI_LIMIT = 16;
export const BLEND_MODES = ["normal", "multiply", "screen", "overlay"] as const;
export type BlendMode = (typeof BLEND_MODES)[number];
export const LOCAL_ADJUSTMENT_ID_PATTERN = /^local_[A-Za-z0-9_-]{1,58}$/;
export const MASK_ID_PATTERN = /^(full|mask_[A-Za-z0-9_-]{1,58})$/;
export const MASK_LIMIT = 20;
export const USER_MASK_ID_PATTERN = /^mask_[A-Za-z0-9_-]{1,58}$/;
export const MASK_SHAPES = ["rectangle", "ellipse"] as const satisfies readonly MaskShape[];
export const SEMANTIC_MASK_HASH = /^[0-9a-f]{64}$/;

export interface AdjustmentRange {
  min: number;
  max: number;
  step: number;
  defaultValue: number;
}

export const ADJUSTMENT_RANGES = {
  exposureEv: { min: -5, max: 5, step: 0.01, defaultValue: 0 },
  contrast: { min: -100, max: 100, step: 1, defaultValue: 0 },
  highlights: { min: -100, max: 100, step: 1, defaultValue: 0 },
  shadows: { min: -100, max: 100, step: 1, defaultValue: 0 },
  whites: { min: -100, max: 100, step: 1, defaultValue: 0 },
  blacks: { min: -100, max: 100, step: 1, defaultValue: 0 },
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

export const HSL_RANGES = {
  hue: { min: -180, max: 180, step: 1, defaultValue: 0 },
  saturation: { min: -100, max: 100, step: 1, defaultValue: 0 },
  luminance: { min: -100, max: 100, step: 1, defaultValue: 0 },
} as const satisfies Record<keyof HslBand, AdjustmentRange>;

export const COLOR_GRADING_RANGES = {
  hue: { min: 0, max: 360, step: 1, defaultValue: 0 },
  saturation: { min: 0, max: 100, step: 1, defaultValue: 0 },
  balance: { min: -100, max: 100, step: 1, defaultValue: 0 },
  blending: { min: 0, max: 100, step: 1, defaultValue: 50 },
} as const;

export const OUTPUT_DEFAULT_QUALITY = 92;

export const DEFAULT_ADJUSTMENTS: Adjustments = {
  exposureEv: 0,
  contrast: 0,
  highlights: 0,
  shadows: 0,
  whites: 0,
  blacks: 0,
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

export const DEFAULT_RECIPE: EditorRecipe = createDefaultRecipe();

export function roundTo2(value: number): number {
  return roundTo(value, 2);
}

export function roundTo4(value: number): number {
  return roundTo(value, 4);
}

export function roundTo6(value: number): number {
  return roundTo(value, 6);
}

function roundTo(value: number, places: number): number {
  if (!Number.isFinite(value)) {
    return 0;
  }
  const factor = 10 ** places;
  return Math.round(value * factor) / factor + 0;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function finite(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function bounded(raw: unknown, range: AdjustmentRange, places = 2): number {
  const value = typeof raw === "number" && Number.isFinite(raw) ? raw : range.defaultValue;
  return roundTo(clamp(value, range.min, range.max), places);
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
    normalized[key] = bounded(source[key], ADJUSTMENT_RANGES[key]);
  }
  normalized.crop = normalizeCrop(source.crop);
  return normalized;
}

export function normalizeCurveChannel(
  points: readonly Partial<CurvePoint>[] | undefined,
): CurvePoint[] {
  if (!Array.isArray(points)) {
    return [];
  }
  const candidates = points
    .filter(
      (point): point is CurvePoint =>
        point !== null &&
        typeof point === "object" &&
        typeof point.x === "number" &&
        Number.isFinite(point.x) &&
        typeof point.y === "number" &&
        Number.isFinite(point.y),
    )
    .map((point) => ({
      x: roundTo6(clamp(point.x, 0, 1)),
      y: roundTo6(clamp(point.y, 0, 1)),
    }))
    .sort((left, right) => left.x - right.x);

  const unique: CurvePoint[] = [];
  for (const point of candidates) {
    const previous = unique[unique.length - 1];
    if (previous && point.x <= previous.x) {
      continue;
    }
    unique.push(point);
    if (unique.length >= CURVE_MAX_POINTS) {
      break;
    }
  }
  return unique.length >= 2 ? unique : [];
}

export function normalizeCurveSet(curve: Partial<CurveSet> | undefined): CurveSet {
  return {
    master: normalizeCurveChannel(curve?.master),
    red: normalizeCurveChannel(curve?.red),
    green: normalizeCurveChannel(curve?.green),
    blue: normalizeCurveChannel(curve?.blue),
  };
}

function normalizeHslBand(band: Partial<HslBand> | undefined): HslBand {
  return {
    hue: bounded(band?.hue, HSL_RANGES.hue),
    saturation: bounded(band?.saturation, HSL_RANGES.saturation),
    luminance: bounded(band?.luminance, HSL_RANGES.luminance),
  };
}

export function normalizeHsl(
  hsl: Partial<HslAdjustments> | undefined,
): Required<HslAdjustments> {
  const normalized = {} as Required<HslAdjustments>;
  for (const band of HSL_BAND_NAMES) {
    normalized[band] = normalizeHslBand(hsl?.[band]);
  }
  return normalized;
}

function normalizeColorGradeZone(zone: Partial<ColorGradeZone> | undefined): ColorGradeZone {
  return {
    hue: bounded(zone?.hue, COLOR_GRADING_RANGES.hue),
    saturation: bounded(zone?.saturation, COLOR_GRADING_RANGES.saturation),
  };
}

export function normalizeColorGrading(
  grading: Partial<ColorGrading> | undefined,
): Required<ColorGrading> {
  return {
    shadows: normalizeColorGradeZone(grading?.shadows),
    midtones: normalizeColorGradeZone(grading?.midtones),
    highlights: normalizeColorGradeZone(grading?.highlights),
    balance: bounded(grading?.balance, COLOR_GRADING_RANGES.balance),
    blending: bounded(grading?.blending, COLOR_GRADING_RANGES.blending),
  };
}

export const MASK_RANGES = {
  feather: { min: 0, max: 100, step: 1, defaultValue: 15 },
  opacity: { min: 0, max: 100, step: 1, defaultValue: 100 },
} as const satisfies Record<"feather" | "opacity", AdjustmentRange>;

export type MaskNumberKey = keyof typeof MASK_RANGES;

export function normalizeMask(mask: Partial<UserMask> | null | undefined): UserMask | null {
  if (!mask) {
    return null;
  }
  const id = typeof mask.id === "string" ? mask.id.trim() : "";
  if (!USER_MASK_ID_PATTERN.test(id)) {
    return null;
  }
  if (mask.source === "semantic") {
    const semanticClass = mask.semanticClass;
    if (
      mask.shape !== "semantic" ||
      (semanticClass !== "person" && semanticClass !== "sky") ||
      typeof mask.matteId !== "string" ||
      !SEMANTIC_MASK_HASH.test(mask.matteId) ||
      typeof mask.matteSha256 !== "string" ||
      !SEMANTIC_MASK_HASH.test(mask.matteSha256) ||
      typeof mask.modelVersion !== "string" ||
      mask.modelVersion.length === 0
    ) {
      return null;
    }
    return {
      id,
      shape: "semantic",
      source: "semantic",
      semanticClass,
      matteId: mask.matteId,
      matteSha256: mask.matteSha256,
      modelVersion: mask.modelVersion,
      coordinateSpace: "source-normalized",
      x: 0,
      y: 0,
      width: 1,
      height: 1,
      feather: bounded(mask.feather, MASK_RANGES.feather),
      opacity: bounded(mask.opacity, MASK_RANGES.opacity),
      inverted: mask.inverted === true,
    };
  }
  const x = roundTo4(clamp(finite(mask.x, 0), 0, 0.9999));
  const y = roundTo4(clamp(finite(mask.y, 0), 0, 0.9999));
  const width = roundTo4(clamp(finite(mask.width, 1), 0.0001, roundTo4(1 - x)));
  const height = roundTo4(clamp(finite(mask.height, 1), 0.0001, roundTo4(1 - y)));
  return {
    id,
    shape: mask.shape === "ellipse" ? "ellipse" : "rectangle",
    source: "user",
    coordinateSpace: "source-normalized",
    x,
    y,
    width,
    height,
    feather: bounded(mask.feather, MASK_RANGES.feather),
    opacity: bounded(mask.opacity, MASK_RANGES.opacity),
    inverted: mask.inverted === true,
  };
}

export function normalizeMasks(
  masks: readonly (Partial<UserMask> | null | undefined)[] | undefined,
): UserMask[] {
  if (!Array.isArray(masks)) {
    return [];
  }
  const seen = new Set<string>();
  const normalized: UserMask[] = [];
  for (const item of masks) {
    const mask = normalizeMask(item);
    if (!mask || seen.has(mask.id)) {
      continue;
    }
    seen.add(mask.id);
    normalized.push(mask);
  }
  normalized.sort((left, right) => (left.id < right.id ? -1 : left.id > right.id ? 1 : 0));
  return normalized.slice(0, MASK_LIMIT);
}

export function createMask(id: string): UserMask {
  return {
    id,
    shape: "rectangle",
    source: "user",
    coordinateSpace: "source-normalized",
    x: 0.25,
    y: 0.25,
    width: 0.5,
    height: 0.5,
    feather: MASK_RANGES.feather.defaultValue,
    opacity: MASK_RANGES.opacity.defaultValue,
    inverted: false,
  };
}

export interface SemanticMaskInfo {
  matteId: string;
  sha256: string;
  modelVersion: string;
  semanticClass: "person" | "sky";
}

export function createSemanticMask(id: string, info: SemanticMaskInfo): UserMask {
  return {
    id,
    shape: "semantic",
    source: "semantic",
    semanticClass: info.semanticClass,
    matteId: info.matteId,
    matteSha256: info.sha256,
    modelVersion: info.modelVersion,
    coordinateSpace: "source-normalized",
    x: 0,
    y: 0,
    width: 1,
    height: 1,
    feather: MASK_RANGES.feather.defaultValue,
    opacity: MASK_RANGES.opacity.defaultValue,
    inverted: false,
  };
}

function nextId(prefix: string, used: ReadonlySet<string>): string {
  let index = 1;
  while (used.has(`${prefix}${index}`)) {
    index += 1;
  }
  return `${prefix}${index}`;
}

export function createMaskId(masks: readonly UserMask[]): string {
  return nextId("mask_", new Set(masks.map((mask) => mask.id)));
}

export function createLocalAdjustmentId(items: readonly LocalAdjustment[]): string {
  return nextId("local_", new Set(items.map((item) => item.id)));
}

export function normalizeLocalAdjustmentValues(
  adjustments: Partial<LocalAdjustments> | undefined,
): LocalAdjustments {
  const normalized = {} as LocalAdjustments;
  for (const key of LOCAL_ADJUSTMENT_KEYS) {
    normalized[key] = 0;
  }
  for (const key of LOCAL_V1_ADJUSTMENT_KEYS) {
    normalized[key] = bounded(adjustments?.[key], ADJUSTMENT_RANGES[key]);
  }
  return normalized;
}

export type LocalAdjustmentInput = Partial<Omit<LocalAdjustment, "adjustments">> & {
  adjustments?: Partial<LocalAdjustments>;
};

export function normalizeLocalAdjustments(
  items: readonly LocalAdjustmentInput[] | undefined,
): LocalAdjustment[] {
  if (!Array.isArray(items)) {
    return [];
  }
  const seen = new Set<string>();
  const normalized: LocalAdjustment[] = [];
  for (const item of items) {
    if (item === null || typeof item !== "object") {
      continue;
    }
    const id = typeof item.id === "string" ? item.id : "";
    if (!LOCAL_ADJUSTMENT_ID_PATTERN.test(id) || seen.has(id)) {
      continue;
    }
    const maskId = typeof item.maskId === "string" ? item.maskId : "";
    if (!MASK_ID_PATTERN.test(maskId)) {
      continue;
    }
    seen.add(id);
    const name =
      typeof item.name === "string" && item.name.trim() !== ""
        ? item.name.trim().slice(0, 200)
        : null;
    const blendMode = BLEND_MODES.includes(item.blendMode as BlendMode)
      ? (item.blendMode as BlendMode)
      : "normal";
    const opacity =
      typeof item.opacity === "number" && Number.isFinite(item.opacity)
        ? roundTo2(clamp(item.opacity, 0, 100))
        : 100;
    const order =
      typeof item.order === "number" &&
      Number.isInteger(item.order) &&
      item.order >= 0 &&
      item.order <= LOCAL_ADJUSTMENT_LIMIT - 1
        ? item.order
        : 0;
    normalized.push({
      id,
      maskId,
      enabled: typeof item.enabled === "boolean" ? item.enabled : true,
      name,
      blendMode,
      opacity,
      order,
      adjustments: normalizeLocalAdjustmentValues(item.adjustments),
    });
  }
  normalized.sort(
    (left, right) =>
      left.order - right.order || (left.id < right.id ? -1 : left.id > right.id ? 1 : 0),
  );
  return normalized.slice(0, LOCAL_ADJUSTMENT_LIMIT);
}

function usesLayerFields(item: LocalAdjustment): boolean {
  return (
    item.name !== null ||
    item.blendMode !== "normal" ||
    item.opacity !== 100 ||
    item.order !== 0
  );
}

function renumberLayers(items: LocalAdjustment[]): LocalAdjustment[] {
  return items.map((item, index) => ({ ...item, order: index }));
}

function finalizeLayers(items: LocalAdjustment[]): LocalAdjustment[] {
  return items.some(usesLayerFields) ? renumberLayers(items) : items;
}

export function normalizeOutput(output: Partial<OutputSettings> | undefined): OutputSettings {
  const quality =
    typeof output?.quality === "number" && Number.isFinite(output.quality)
      ? Math.round(output.quality)
      : OUTPUT_DEFAULT_QUALITY;
  return {
    format: output?.format === "png" ? "png" : "jpeg",
    quality: clamp(quality, 1, 100),
    colorSpace: "sRGB",
  };
}

function normalizeStyleId(styleId: EditRecipe["styleId"] | undefined): EditRecipe["styleId"] {
  return styleId && STYLE_IDS.some((candidate) => candidate === styleId) ? styleId : "natural";
}

function normalizeNotes(notes: string[] | undefined): string[] {
  if (!Array.isArray(notes)) {
    return [];
  }
  return notes
    .filter((note): note is string => typeof note === "string")
    .map((note) => note.slice(0, 200))
    .slice(0, 8);
}

export function normalizeRecipe(recipe: Partial<EditRecipe> | undefined): EditorRecipe {
  return {
    schemaVersion: "2.0",
    styleId: normalizeStyleId(recipe?.styleId),
    styleStrength: roundTo2(clamp(recipe?.styleStrength ?? 0, 0, 100)),
    adjustments: normalizeAdjustments(recipe?.adjustments),
    curve: normalizeCurveSet(recipe?.curve),
    hsl: normalizeHsl(recipe?.hsl),
    colorGrading: normalizeColorGrading(recipe?.colorGrading),
    masks: normalizeMasks(recipe?.masks),
    localAdjustments: normalizeLocalAdjustments(recipe?.localAdjustments),
    output: normalizeOutput(recipe?.output),
    rationale: normalizeNotes(recipe?.rationale),
    warnings: normalizeNotes(recipe?.warnings),
  };
}

export function createDefaultRecipe(): EditorRecipe {
  return normalizeRecipe({});
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

export function withCurveSet(recipe: EditRecipe, curve: Partial<CurveSet>): EditorRecipe {
  return normalizeRecipe({
    ...recipe,
    curve: normalizeCurveSet(curve),
  });
}

export function withCurve(
  recipe: EditRecipe,
  channel: keyof CurveSet,
  points: readonly CurvePoint[],
): EditorRecipe {
  return withCurveSet(recipe, {
    ...normalizeCurveSet(recipe.curve),
    [channel]: [...points],
  });
}

export function withHslSet(recipe: EditRecipe, hsl: Partial<HslAdjustments>): EditorRecipe {
  return normalizeRecipe({
    ...recipe,
    hsl: normalizeHsl(hsl),
  });
}

export function withHsl(
  recipe: EditRecipe,
  band: keyof HslAdjustments,
  key: keyof HslBand,
  value: number,
): EditorRecipe {
  const range = HSL_RANGES[key];
  const current = normalizeHsl(recipe.hsl);
  return withHslSet(recipe, {
    ...current,
    [band]: {
      ...current[band],
      [key]: roundTo2(clamp(value, range.min, range.max)),
    },
  });
}

export function withColorGradingSet(
  recipe: EditRecipe,
  grading: Partial<ColorGrading>,
): EditorRecipe {
  return normalizeRecipe({
    ...recipe,
    colorGrading: normalizeColorGrading(grading),
  });
}

export function withColorGradeZone(
  recipe: EditRecipe,
  zone: ColorGradeZoneName,
  key: keyof ColorGradeZone,
  value: number,
): EditorRecipe {
  const range = COLOR_GRADING_RANGES[key];
  const current = normalizeColorGrading(recipe.colorGrading);
  return withColorGradingSet(recipe, {
    ...current,
    [zone]: {
      ...current[zone],
      [key]: roundTo2(clamp(value, range.min, range.max)),
    },
  });
}

export type MaskPatch = Partial<
  Pick<UserMask, "shape" | "x" | "y" | "width" | "height" | "feather" | "opacity" | "inverted">
>;

export function addMask(recipe: EditRecipe, mask: UserMask): EditorRecipe {
  return normalizeRecipe({
    ...recipe,
    masks: [...normalizeMasks(recipe.masks), mask],
  });
}

export function updateMask(recipe: EditRecipe, id: string, patch: MaskPatch): EditorRecipe {
  return normalizeRecipe({
    ...recipe,
    masks: recipe.masks.map((mask) => (mask.id === id ? { ...mask, ...patch } : mask)),
  });
}

export function removeMask(recipe: EditRecipe, id: string): EditorRecipe {
  return normalizeRecipe({
    ...recipe,
    masks: recipe.masks.filter((mask) => mask.id !== id),
    // An adjustment pointing at a deleted mask is silently skipped by the
    // renderer while still reading "enabled" in the panel, so it goes with it.
    localAdjustments: finalizeLayers(
      normalizeLocalAdjustments(recipe.localAdjustments).filter(
        (item) => item.maskId === "full" || item.maskId !== id,
      ),
    ),
  });
}

export function addLocalAdjustment(
  recipe: EditRecipe,
  maskId = "full",
  adjustments: Partial<LocalAdjustments> = {},
): EditorRecipe {
  // Normalize before appending: sparse legacy orders such as [1, 2] would
  // otherwise produce a duplicate order and fail backend validation.
  const existing = renumberLayers(normalizeLocalAdjustments(recipe.localAdjustments));
  const id = createLocalAdjustmentId(recipe.localAdjustments);
  return normalizeRecipe({
    ...recipe,
    localAdjustments: [
      ...existing,
      {
        id,
        maskId: MASK_ID_PATTERN.test(maskId) ? maskId : "full",
        enabled: true,
        name: null,
        blendMode: "normal",
        opacity: 100,
        order: existing.length,
        adjustments: normalizeLocalAdjustmentValues(adjustments),
      },
    ],
  });
}

export function updateLocalAdjustment(
  recipe: EditRecipe,
  id: string,
  key: LocalV1AdjustmentKey,
  value: number,
): EditorRecipe {
  const range = ADJUSTMENT_RANGES[key];
  return normalizeRecipe({
    ...recipe,
    localAdjustments: normalizeLocalAdjustments(recipe.localAdjustments).map((item) =>
      item.id === id
        ? {
            ...item,
            adjustments: {
              ...normalizeLocalAdjustmentValues(item.adjustments),
              [key]: roundTo2(clamp(value, range.min, range.max)),
            },
          }
        : item,
    ),
  });
}

export function setLocalAdjustmentEnabled(
  recipe: EditRecipe,
  id: string,
  enabled: boolean,
): EditorRecipe {
  return normalizeRecipe({
    ...recipe,
    localAdjustments: normalizeLocalAdjustments(recipe.localAdjustments).map((item) =>
      item.id === id ? { ...item, enabled } : item,
    ),
  });
}

export function setLocalAdjustmentMask(
  recipe: EditRecipe,
  id: string,
  maskId: string,
): EditorRecipe {
  const nextMaskId = MASK_ID_PATTERN.test(maskId) ? maskId : "full";
  return normalizeRecipe({
    ...recipe,
    localAdjustments: normalizeLocalAdjustments(recipe.localAdjustments).map((item) =>
      item.id === id ? { ...item, maskId: nextMaskId } : item,
    ),
  });
}

export function resetLocalAdjustment(recipe: EditRecipe, id: string): EditorRecipe {
  return normalizeRecipe({
    ...recipe,
    localAdjustments: normalizeLocalAdjustments(recipe.localAdjustments).map((item) =>
      item.id === id
        ? { ...item, adjustments: normalizeLocalAdjustmentValues({}) }
        : item,
    ),
  });
}

export function removeLocalAdjustment(recipe: EditRecipe, id: string): EditorRecipe {
  const remaining = finalizeLayers(
    normalizeLocalAdjustments(recipe.localAdjustments).filter((item) => item.id !== id),
  );
  const referenced = new Set(remaining.map((item) => item.maskId));
  return normalizeRecipe({
    ...recipe,
    masks: recipe.masks.filter((mask) => referenced.has(mask.id)),
    localAdjustments: remaining,
  });
}

export function moveLocalAdjustment(
  recipe: EditRecipe,
  id: string,
  direction: -1 | 1,
): EditorRecipe {
  const items = normalizeLocalAdjustments(recipe.localAdjustments);
  const index = items.findIndex((item) => item.id === id);
  const target = index + direction;
  if (index < 0 || target < 0 || target >= items.length) {
    return normalizeRecipe(recipe);
  }
  const reordered = [...items];
  [reordered[index], reordered[target]] = [reordered[target], reordered[index]];
  return normalizeRecipe({
    ...recipe,
    localAdjustments: renumberLayers(reordered),
  });
}

export function setLocalAdjustmentBlendMode(
  recipe: EditRecipe,
  id: string,
  blendMode: BlendMode,
): EditorRecipe {
  const nextMode = BLEND_MODES.includes(blendMode) ? blendMode : "normal";
  return normalizeRecipe({
    ...recipe,
    localAdjustments: normalizeLocalAdjustments(recipe.localAdjustments).map((item) =>
      item.id === id ? { ...item, blendMode: nextMode } : item,
    ),
  });
}

export function setLocalAdjustmentOpacity(
  recipe: EditRecipe,
  id: string,
  opacity: number,
): EditorRecipe {
  const nextOpacity = roundTo2(clamp(opacity, 0, 100));
  return normalizeRecipe({
    ...recipe,
    localAdjustments: normalizeLocalAdjustments(recipe.localAdjustments).map((item) =>
      item.id === id ? { ...item, opacity: nextOpacity } : item,
    ),
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
