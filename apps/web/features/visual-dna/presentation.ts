import { SCENE_LABELS } from "@/features/master-vision/presentation";
import type {
  PersonalAvoidEffect,
  PersonalStyleAnalysisStatus,
  PersonalStyleChangeSource,
  PersonalStyleSource,
  PersonalStyleStatus,
  PhotoVisualFeatures,
} from "@/types/personal-style";

export const STYLE_STATUS_LABELS: Record<PersonalStyleStatus, string> = {
  draft: "草稿",
  published: "已发布",
  disabled: "已停用",
};

export const SOURCE_LABELS: Record<PersonalStyleSource, string> = {
  photos: "参考照片",
  custom: "自然语言",
  mixed: "风格混合",
  evolution: "反馈演变",
};

export const ANALYSIS_STATUS_LABELS: Record<PersonalStyleAnalysisStatus, string> = {
  completed: "已完成",
  pending: "等待中",
  processing: "分析中",
  failed: "失败",
  missing: "参考照片已删除",
  analysis_required: "待分析",
};

export const CHANGE_SOURCE_LABELS: Record<PersonalStyleChangeSource, string> = {
  analysis: "参考照片融合",
  user: "手动编辑",
  custom: "自然语言创建",
  mix: "风格混合",
  evolution: "反馈演变",
  restore: "版本恢复",
};

export const AVOID_LABELS: Record<PersonalAvoidEffect, string> = {
  oversaturated: "过饱和",
  crushed_blacks: "压黑暗部",
  clipped_highlights: "高光溢出",
  color_cast: "明显偏色",
  unnatural_skin: "肤色不自然",
  heavy_filter: "明显滤镜感",
  over_sharpened: "过度锐化",
  flat_contrast: "反差过强",
};

export const AVOID_OPTIONS = Object.entries(AVOID_LABELS) as Array<
  [PersonalAvoidEffect, string]
>;

export const CONSTRAINT_LABELS: Record<string, string> = {
  preserve_skin_tone: "保护肤色",
  preserve_highlight_detail: "保护高光细节",
  preserve_shadow_detail: "保护暗部细节",
  avoid_extreme_saturation: "避免极端饱和度",
  avoid_extreme_contrast: "避免极端反差",
  keep_ambient_color: "保留环境色",
  natural_look: "保持自然观感",
  avoid_color_cast: "避免明显偏色",
  maintain_neutrality: "保持中性白平衡",
  keep_low_key: "保持低调",
  keep_warm_tones: "保留暖调",
};

export const FEATURE_ORIGIN_LABELS: Record<string, string> = {
  measurement: "客观测量",
  model: "模型判断",
  derived: "派生判断",
};

export const FEATURE_CATEGORY_LABELS: Record<string, string> = {
  color: "色彩",
  tone: "影调",
  light: "光线",
  texture: "质感",
  scene: "场景",
  composition: "构图",
};

export const STABILITY_LABELS: Record<string, string> = {
  color: "色彩",
  tone: "影调",
  light: "光线",
  texture: "质感",
  scene: "场景",
};

export type TraitKey =
  | "colorTendency"
  | "colorRelationships"
  | "colorSaturation"
  | "lightContrast"
  | "lightShadows"
  | "lightHighlights"
  | "lightExpression"
  | "textureGrain"
  | "textureSharpness"
  | "textureDetail";

export type TraitValues = Record<TraitKey, string>;

export const TRAIT_FIELDS: Array<{
  key: TraitKey;
  label: string;
  placeholder: string;
}> = [
  { key: "colorTendency", label: "色彩倾向", placeholder: "例如：低饱和、偏冷" },
  { key: "colorRelationships", label: "色彩关系", placeholder: "例如：环境色自然，避免强对比" },
  { key: "colorSaturation", label: "饱和度表达", placeholder: "例如：低饱和，保留少量色彩" },
  { key: "lightContrast", label: "影调反差", placeholder: "例如：中等反差，保留暗部" },
  { key: "lightShadows", label: "暗部表现", placeholder: "例如：暗部较深但有层次" },
  { key: "lightHighlights", label: "高光表现", placeholder: "例如：高光柔和，不溢出" },
  { key: "lightExpression", label: "光线表达", placeholder: "例如：自然侧光，重视明暗关系" },
  { key: "textureGrain", label: "颗粒", placeholder: "例如：颗粒克制" },
  { key: "textureSharpness", label: "锐度", placeholder: "例如：清晰度自然" },
  { key: "textureDetail", label: "细节", placeholder: "例如：保留自然细节" },
];

export function traitValuesFrom(profile: {
  color: { tendency: string; relationships: string; saturation: string };
  light: { contrast: string; shadows: string; highlights: string; expression: string };
  texture: { grain: string; sharpness: string; detail: string };
}): TraitValues {
  return {
    colorTendency: profile.color.tendency,
    colorRelationships: profile.color.relationships,
    colorSaturation: profile.color.saturation,
    lightContrast: profile.light.contrast,
    lightShadows: profile.light.shadows,
    lightHighlights: profile.light.highlights,
    lightExpression: profile.light.expression,
    textureGrain: profile.texture.grain,
    textureSharpness: profile.texture.sharpness,
    textureDetail: profile.texture.detail,
  };
}

export interface TargetField {
  key: string;
  label: string;
  min: number;
  max: number;
  step: number;
}

export const TARGET_FIELDS: TargetField[] = [
  { key: "saturation", label: "饱和度", min: -100, max: 100, step: 1 },
  { key: "vibrance", label: "自然饱和度", min: -50, max: 50, step: 1 },
  { key: "contrast", label: "对比度", min: -30, max: 30, step: 1 },
  { key: "highlights", label: "高光", min: -40, max: 40, step: 1 },
  { key: "shadows", label: "暗部", min: -40, max: 40, step: 1 },
  { key: "temperature", label: "色温", min: -20, max: 20, step: 1 },
  { key: "tint", label: "色调", min: -15, max: 15, step: 1 },
  { key: "grain", label: "颗粒", min: 0, max: 30, step: 1 },
  { key: "clarity", label: "清晰度", min: -15, max: 15, step: 1 },
];

export function targetLabel(key: string): string {
  return TARGET_FIELDS.find((field) => field.key === key)?.label ?? key;
}

export function sceneLabel(scene: string): string {
  return SCENE_LABELS[scene as keyof typeof SCENE_LABELS] ?? scene;
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "—";
  }
  return `${Math.round(value * 100)}%`;
}

export function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleString("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatTargetValue(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  return rounded > 0 ? `+${rounded}` : String(rounded);
}

export function featureSummary(features: PhotoVisualFeatures): string {
  return [
    `色彩 ${Math.round(features.color.saturationMean * 100)}%`,
    `反差 ${Math.round(features.tone.contrastStrength * 100)}%`,
    `清晰度 ${Math.round(features.texture.sharpness * 100)}%`,
  ].join(" · ");
}

export function formatChangeValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "—";
  }
  if (typeof value === "string") {
    return value.length > 80 ? `${value.slice(0, 77)}…` : value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  const serialized = JSON.stringify(value);
  return serialized.length > 80 ? `${serialized.slice(0, 77)}…` : serialized;
}
