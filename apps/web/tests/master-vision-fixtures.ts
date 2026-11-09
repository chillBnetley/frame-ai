import { normalizeRecipe, DEFAULT_ADJUSTMENTS } from "@/lib/recipe";
import type { PhotographerPlanResponse } from "@/types/photographer";
import type {
  ConversionModeListResponse,
  StyleDetailResponse,
  StyleFitResponse,
  StyleLibraryItem,
  StyleProfile,
} from "@/types/style-library";

import { ANALYSIS_ID } from "./analysis-fixtures";
import { photographerPlan } from "./photographer-fixtures";
import { IMAGE_ID, SESSION_ID } from "./session-fixtures";

export const MASTER_STYLE_ID = "fan_ho";
export const GENRE_STYLE_ID = "environmental_portrait";

export function styleItem(overrides: Partial<StyleLibraryItem> = {}): StyleLibraryItem {
  return {
    id: MASTER_STYLE_ID,
    kind: "master",
    version: "1.0",
    name: "Fan Ho 光影几何",
    description: "以方向性光线、几何阴影与孤身人物构建街头戏剧。",
    category: "creative",
    signature: ["高对比黑白", "几何阴影", "方向性光带"],
    suitableScenes: ["street", "architecture"],
    engineStyle: "street",
    defaultStrength: 0.6,
    enabled: true,
    favorite: false,
    ...overrides,
  };
}

export const GENRE_ITEM = styleItem({
  id: GENRE_STYLE_ID,
  kind: "genre",
  name: "环境人像",
  description: "保留人物与环境的关系，用温和影调突出主体。",
  category: "scene",
  signature: ["自然肤色", "环境光", "轻压背景"],
  suitableScenes: ["portrait", "street", "indoor"],
  engineStyle: "portrait",
  defaultStrength: 0.5,
});

export function styleProfile(overrides: Partial<StyleProfile> = {}): StyleProfile {
  return {
    id: MASTER_STYLE_ID,
    kind: "master",
    version: "1.0",
    name: "Fan Ho 光影几何",
    description: "以方向性光线、几何阴影与孤身人物构建街头戏剧。",
    philosophy: "光是主角：在街道与建筑间等待光束切开空间的瞬间。",
    color: {
      tendency: "黑白影调为核心",
      relationships: "明暗关系取代色彩关系",
      saturation: "去饱和至单色",
    },
    light: {
      contrast: "高对比，明暗交界清晰",
      shadows: "大面积深阴影",
      highlights: "集中受光区",
      expression: "低角度直射光形成的长影与光带",
    },
    composition: {
      space: "前景暗部框景",
      geometry: "强烈对角线",
      negativeSpace: "暗部留白衬托人物",
      subjectRelation: "人物置于光区",
    },
    texture: {
      grain: "经典银盐颗粒",
      sharpness: "适中偏锐",
      detail: "两端保留层次",
    },
    sceneFit: {
      suitable: ["street", "architecture"],
      suitableNotes: "存在明显方向性光线与建筑结构。",
      unsuitableNotes: "光线平坦、缺少几何结构的照片。",
    },
    postStrategy: "可转黑白并用 S 曲线拉开影调，局部曝光突出已有光区。",
    captureTechniques: "不能凭空创造真实光源、光束方向或人物姿态。",
    constraints: ["preserve_highlight_detail", "preserve_shadow_detail", "maintain_neutrality"],
    preserveNotes: "不破坏人物身份与现场光线方向。",
    sources: [
      {
        title: "FRAME AI 大师风格原创研究",
        url: null,
        license: "风格研究原创整理；不复制原作。",
      },
    ],
    engineStyle: "street",
    envelope: {
      exposureEv: 1,
      contrast: 40,
      highlights: 30,
      shadows: 35,
      whites: 25,
      blacks: 30,
      temperature: 15,
      tint: 10,
      saturation: 100,
      vibrance: 15,
      clarity: 25,
      denoise: 25,
      vignette: 15,
      grain: 12,
    },
    defaultStrength: 0.6,
    enabled: true,
    ...overrides,
  };
}

export function styleDetail(overrides: Partial<StyleDetailResponse> = {}): StyleDetailResponse {
  return {
    style: styleProfile(),
    favorite: false,
    ...overrides,
  };
}

export function styleFit(overrides: Partial<StyleFitResponse> = {}): StyleFitResponse {
  return {
    schemaVersion: "stage6/1",
    engineVersion: "style-fit/1",
    imageId: IMAGE_ID,
    analysisId: ANALYSIS_ID,
    isMock: true,
    styleId: MASTER_STYLE_ID,
    styleName: "Fan Ho 光影几何",
    styleKind: "master",
    styleVersion: "1.0",
    overallScore: 72,
    overallLevel: "high",
    summary: "街道场景与强光影结构为风格提供了良好的基础。",
    dimensions: [
      { dimension: "color", level: "high", score: 78, basis: "黑白转换与中性灰阶匹配。", evidenceRefs: ["color.saturation"] },
      { dimension: "light", level: "high", score: 80, basis: "方向性光线支持明暗塑造。", evidenceRefs: ["lighting.direction"] },
      { dimension: "scene", level: "high", score: 82, basis: "街头场景符合档案。", evidenceRefs: ["scene.primary"] },
      { dimension: "composition", level: "medium", score: 58, basis: "建筑线条提供结构。", evidenceRefs: ["composition.balance"] },
      { dimension: "subject", level: "medium", score: 55, basis: "人物可置于光区。", evidenceRefs: ["subjects"] },
    ],
    conflicts: [
      {
        dimension: "composition",
        description: "前景遮挡较少，可利用的框景有限。",
        evidenceRefs: ["composition.occlusion"],
        improvable: false,
      },
    ],
    achievable: ["黑白影调", "明暗对比"],
    unachievable: ["不存在的光束"],
    recommendedMode: "style",
    recommendedStrength: { minimum: 0.4, maximum: 0.75, default: 0.6 },
    alternatives: [
      {
        styleId: GENRE_STYLE_ID,
        name: "环境人像",
        kind: "genre",
        score: 66,
        level: "medium",
        reason: "人物与环境的比例更适合环境人像。",
      },
    ],
    limitations: [],
    ...overrides,
  };
}

export function conversionModeList(): ConversionModeListResponse {
  return {
    modes: [
      {
        mode: "natural",
        name: "Natural 真实优先",
        description: "温和曝光与色彩，保护高光、阴影和肤色。",
        allowedAdjustments: ["exposureEv", "contrast", "saturation"],
        forbiddenOperations: ["生成式填充与移除真实物体"],
        preservationConstraints: ["natural_look", "preserve_skin_tone"],
        recommendedStrengthMin: 0.2,
        recommendedStrengthMax: 0.7,
        recommendedStrengthDefault: 0.45,
        envelopeScale: 0.6,
      },
      {
        mode: "style",
        name: "Style 风格优先",
        description: "让目标风格的色彩关系与影调清晰可见。",
        allowedAdjustments: ["exposureEv", "contrast", "saturation"],
        forbiddenOperations: ["生成式填充与移除真实物体"],
        preservationConstraints: ["preserve_highlight_detail"],
        recommendedStrengthMin: 0.4,
        recommendedStrengthMax: 0.9,
        recommendedStrengthDefault: 0.65,
        envelopeScale: 1,
      },
      {
        mode: "creative",
        name: "Creative 创意优先",
        description: "在阶段四引擎边界内强化色彩、明暗与局部氛围。",
        allowedAdjustments: ["exposureEv", "contrast", "saturation"],
        forbiddenOperations: ["生成式填充与移除真实物体"],
        preservationConstraints: ["preserve_highlight_detail"],
        recommendedStrengthMin: 0.55,
        recommendedStrengthMax: 1,
        recommendedStrengthDefault: 0.8,
        envelopeScale: 1.25,
      },
    ],
  };
}

export function masterVisionPlan(): PhotographerPlanResponse {
  return photographerPlan({
    analysisId: ANALYSIS_ID,
    sessionId: SESSION_ID,
    imageId: IMAGE_ID,
    mode: "style",
    styleId: MASTER_STYLE_ID,
    styleVersion: "1.0",
    styleStrength: 0.6,
    conversionMode: "style",
    direction: {
      id: "fan_ho_direction",
      name: "Fan Ho 光影几何",
      category: "creative",
      description: "用黑白影调与局部明暗突出已有光区。",
      strength: 0.6,
      constraints: ["preserve_highlight_detail", "preserve_shadow_detail"],
    },
    recipe: normalizeRecipe({
      adjustments: { ...DEFAULT_ADJUSTMENTS, contrast: 16, saturation: -100, shadows: 8 },
    }),
    changes: [
      {
        path: "adjustments.saturation",
        previous: 0,
        proposed: -100,
        reason: "将画面转为中性黑白影调。",
        evidenceRefs: ["color.saturation"],
      },
      {
        path: "adjustments.contrast",
        previous: 0,
        proposed: 16,
        reason: "强化已有明暗结构。",
        evidenceRefs: ["lighting.direction"],
      },
    ],
  });
}
