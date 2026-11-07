import { DEFAULT_ADJUSTMENTS, normalizeRecipe } from "@/lib/recipe";
import type {
  CritiqueApplyResponse,
  PhotographerCritique,
  PhotographerPatchResponse,
  PhotographerPlanResponse,
  PhotographerStyle,
} from "@/types/photographer";

import { ANALYSIS_ID } from "./analysis-fixtures";
import { IMAGE_ID, SESSION_ID } from "./session-fixtures";

export const PLAN_ID = "88888888-8888-4888-8888-888888888888";
export const PATCH_ID = "77777777-7777-4777-7777-777777777777";

export function photographerStyle(
  overrides: Partial<PhotographerStyle> = {},
): PhotographerStyle {
  return {
    id: "portrait",
    version: "1.0",
    name: "自然人像",
    category: "scene",
    description: "保留自然肤色，平衡人物曝光与背景层次。",
    supportedScenes: ["portrait", "indoor"],
    defaultStrength: 0.5,
    constraints: ["preserve_skin_tone", "preserve_highlight_detail"],
    engineStyle: "portrait",
    enabled: true,
    ...overrides,
  };
}

/** A small stand-in for the backend catalog: enough entries to exercise grouping. */
export function styleCatalog(): PhotographerStyle[] {
  return [
    photographerStyle(),
    photographerStyle({
      id: "clear_portrait",
      name: "清透人像",
      description: "提亮阴影、压低高光，让人物看起来更通透。",
      defaultStrength: 0.55,
    }),
    photographerStyle({
      id: "landscape",
      name: "风光",
      category: "scene",
      description: "强化层次与空间感，保留天空与暗部细节。",
      supportedScenes: ["landscape", "nature", "architecture"],
      defaultStrength: 0.55,
      engineStyle: "landscape",
    }),
    photographerStyle({
      id: "street",
      name: "街头",
      category: "scene",
      description: "提高反差，保留环境的纪实感。",
      supportedScenes: ["street", "night"],
      engineStyle: "street",
    }),
    photographerStyle({
      id: "monochrome",
      name: "黑白纪实",
      category: "creative",
      description: "完全去饱和，只用影调关系重建画面。",
      supportedScenes: ["portrait", "street", "night", "architecture"],
      defaultStrength: 0.7,
      engineStyle: "documentary",
    }),
    photographerStyle({
      id: "cinematic",
      name: "电影叙事",
      category: "creative",
      description: "青橙分级与柔和反差，营造叙事氛围。",
      supportedScenes: ["night", "indoor", "other"],
      defaultStrength: 0.65,
      engineStyle: "cinematic",
    }),
  ];
}

export function photographerPlan(
  overrides: Partial<PhotographerPlanResponse> = {},
): PhotographerPlanResponse {
  return {
    schemaVersion: "stage5/1",
    planId: PLAN_ID,
    analysisId: ANALYSIS_ID,
    sessionId: SESSION_ID,
    imageId: IMAGE_ID,
    mode: "auto",
    isMock: true,
    degraded: false,
    provider: {
      name: "mock",
      model: "mock-planner",
      promptVersion: "planner/mock/1",
    },
    diagnosis: {
      confirmed: [
        {
          issueId: "issue_contrast",
          type: "flat_lighting",
          severity: "medium",
          confidence: 0.7,
          evidence: "画面反差偏低，主体与背景层次不足。",
          evidenceRefs: ["analysis.lighting.contrast"],
        },
      ],
      possible: [],
      creativeChoices: [],
      confidence: 0.6,
      confidenceNote: "启发式置信度，不是校准概率。",
    },
    direction: {
      id: "natural_balance",
      name: "自然平衡",
      category: "scene",
      description: "轻微增强层次，同时保持自然观感。",
      strength: 0.5,
      constraints: [],
    },
    recipe: normalizeRecipe({
      adjustments: { ...DEFAULT_ADJUSTMENTS, contrast: 12 },
    }),
    changes: [
      {
        path: "adjustments.contrast",
        previous: 0,
        proposed: 12,
        reason: "根据诊断证据调整对比度。",
        evidenceRefs: ["analysis.lighting.contrast"],
      },
    ],
    warnings: [],
    limitations: [],
    confidence: 0.6,
    confidenceNote: "启发式置信度，不是校准概率。",
    ...overrides,
  };
}

export function noChangePlan(): PhotographerPlanResponse {
  return photographerPlan({
    changes: [],
    recipe: normalizeRecipe({}),
  });
}

export function photographerPatch(
  overrides: Partial<PhotographerPatchResponse> = {},
): PhotographerPatchResponse {
  return {
    schemaVersion: "stage5/1",
    patchId: PATCH_ID,
    planId: PLAN_ID,
    supported: true,
    recipe: normalizeRecipe({
      adjustments: { ...DEFAULT_ADJUSTMENTS, saturation: -8 },
    }),
    changes: [
      {
        path: "adjustments.saturation",
        previous: 0,
        proposed: -8,
        reason: "按指令调整饱和度。",
        evidenceRefs: ["instruction"],
      },
    ],
    reason: "只移动了饱和度这一个参数，其他调整保持原样。",
    warnings: [],
    limitations: [],
    unsupported: [],
    ...overrides,
  };
}

export function unsupportedPatch(
  overrides: Partial<PhotographerPatchResponse> = {},
): PhotographerPatchResponse {
  return photographerPatch({
    supported: false,
    changes: [],
    recipe: normalizeRecipe({}),
    reason: "移除画面内容不属于参数调整，这个能力不提供。",
    limitations: ["只能调整颜色与影调参数，不能改动像素内容。"],
    unsupported: ["删除或移动画面中的物体"],
    ...overrides,
  });
}

/** The backlit-portrait shape the deterministic critique returns. */
export function photographerCritique(
  overrides: Partial<PhotographerCritique> = {},
): PhotographerCritique {
  return {
    analysisId: ANALYSIS_ID,
    isMock: true,
    generatedBy: "deterministic-rules",
    strengths: [
      {
        text: "高光与暗部几乎没有裁切，层次保留完整。",
        evidenceRefs: [
          "measurement.clipping.highlightsPct",
          "measurement.clipping.shadowsPct",
        ],
      },
    ],
    technical: {
      objective: [
        {
          text: "曝光判定为均衡，中位亮度 0.42。",
          evidenceRefs: ["technicalQuality.exposure", "measurement.luminance.p50"],
        },
      ],
      possibleIssues: [
        {
          text: "高光溢出（高，置信度 85%）：高光裁切占比 4.2%；测量值支持该判断。",
          evidenceRefs: ["issue_hl", "measurement.clipping.highlightsPct"],
        },
      ],
    },
    creative: [
      {
        text: "逆光带来的轮廓可能是这张照片的情绪来源。",
        evidenceRefs: ["lighting.direction"],
        subjective: true,
      },
    ],
    suggestions: [
      {
        text: "轻微压低高光以保留天空层次。",
        category: "exposure",
        evidenceRefs: ["issue_hl", "measurement.clipping.highlightsPct"],
        recipePatch: { highlights: -20, whites: -8 },
      },
      {
        text: "把主体移到三分线附近，留出视线空间。",
        category: "composition",
        evidenceRefs: ["issue_place"],
        recipePatch: null,
      },
    ],
    limitations: ["创作评价是主观判断，不代表客观质量结论。"],
    ...overrides,
  };
}

export function critiqueApply(
  overrides: Partial<CritiqueApplyResponse> = {},
): CritiqueApplyResponse {
  return {
    schemaVersion: "stage5/1",
    patchId: PATCH_ID,
    recipe: normalizeRecipe({
      adjustments: { ...DEFAULT_ADJUSTMENTS, highlights: -20, whites: -8 },
    }),
    changes: [
      {
        path: "adjustments.highlights",
        previous: 0,
        proposed: -20,
        reason: "按点评建议调整，只移动该建议涉及的参数。",
        evidenceRefs: ["instruction"],
      },
      {
        path: "adjustments.whites",
        previous: 0,
        proposed: -8,
        reason: "按点评建议调整，只移动该建议涉及的参数。",
        evidenceRefs: ["instruction"],
      },
    ],
    reason: "按点评建议调整，只移动该建议涉及的参数。",
    warnings: [],
    limitations: [
      "点评建议只调整全局参数，不会改动曲线、HSL、色彩分级、裁切与蒙版。",
    ],
    unsupported: [],
    ...overrides,
  };
}
