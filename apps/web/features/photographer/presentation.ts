import type {
  FeedbackAction,
  FeedbackDimension,
  FeedbackSource,
  PhotographerStyle,
  SceneLabel,
  StyleCategory,
} from "@/types/photographer";

export const STYLE_CATEGORY_LABELS: Record<StyleCategory, string> = {
  scene: "场景风格",
  creative: "创作风格",
};

export const PARAMETERIZED_STYLE_NOTE =
  "风格由参数组合实时计算，不依赖 LUT 或滤镜文件，可随时逐项修改。";

export const ZERO_STRENGTH_NOTE =
  "强度 0 时不叠加任何风格参数，方案只包含针对诊断问题的调整。";

export interface StyleGroups {
  recommended: readonly PhotographerStyle[];
  others: readonly PhotographerStyle[];
}

/**
 * Styles whose `supportedScenes` include the analyzed scene lead the picker; the
 * rest stay selectable, because a look that does not fit the detected scene is
 * still the user's call.
 */
export function groupStylesByScene(
  styles: readonly PhotographerStyle[],
  scene: SceneLabel | null,
): StyleGroups {
  if (scene === null) {
    return { recommended: [], others: styles };
  }
  const recommended = styles.filter((style) =>
    style.supportedScenes.includes(scene),
  );
  const recommendedIds = new Set(recommended.map((style) => style.id));
  return {
    recommended,
    others: styles.filter((style) => !recommendedIds.has(style.id)),
  };
}

export function findStyle(
  styles: readonly PhotographerStyle[],
  styleId: string | null,
): PhotographerStyle | null {
  if (styleId === null) {
    return null;
  }
  return styles.find((style) => style.id === styleId) ?? null;
}

export const PARAMETER_PATH_LABELS: Record<string, string> = {
  "adjustments.exposureEv": "曝光",
  "adjustments.contrast": "对比度",
  "adjustments.highlights": "高光",
  "adjustments.shadows": "阴影",
  "adjustments.whites": "白色色阶",
  "adjustments.blacks": "黑色色阶",
  "adjustments.temperature": "色温",
  "adjustments.tint": "色调",
  "adjustments.saturation": "饱和度",
  "adjustments.vibrance": "自然饱和度",
  "adjustments.clarity": "清晰度",
  "adjustments.sharpen": "锐化",
  "adjustments.denoise": "降噪",
  "adjustments.vignette": "暗角",
  "adjustments.grain": "颗粒",
  "curve.master": "主曲线",
  colorGrading: "色彩分级",
};

/** A dotted recipe path, shown the way the change lists show it. */
export function changeLabel(path: string): string {
  const local = /^localAdjustments\.([^.]*)\.(.+)$/.exec(path);
  if (local) {
    return `局部 ${local[1]} · ${PARAMETER_PATH_LABELS[`adjustments.${local[2]}`] ?? local[2]}`;
  }
  return PARAMETER_PATH_LABELS[path] ?? path;
}

export const FEEDBACK_ACTION_LABELS: Record<FeedbackAction, string> = {
  accepted: "已接受",
  rejected: "已拒绝",
  modified: "接受后又手动调整",
  reset: "已重置",
};

export const FEEDBACK_SOURCE_LABELS: Record<FeedbackSource, string> = {
  plan: "摄影方案",
  chat: "对话调整",
  critique: "点评应用",
};

export const SCORE_LABELS: Record<number, string> = {
  1: "很差",
  2: "偏差",
  3: "尚可",
  4: "较好",
  5: "很好",
};

export interface FeedbackDimensionOption {
  key: FeedbackDimension;
  label: string;
}

/**
 * The 10 subjective dimensions of the stage-5 rubric. They measure what the
 * user thinks, not an objective quality score.
 */
export const FEEDBACK_DIMENSIONS: readonly FeedbackDimensionOption[] = [
  { key: "exposure", label: "曝光" },
  { key: "color", label: "色彩" },
  { key: "skinTone", label: "肤色" },
  { key: "highlights", label: "高光" },
  { key: "shadows", label: "阴影" },
  { key: "subject", label: "主体" },
  { key: "localAdjustment", label: "局部调整" },
  { key: "style", label: "风格" },
  { key: "naturalness", label: "自然度" },
  { key: "creativeIntent", label: "创作意图" },
];

export const FEEDBACK_PRIVACY_NOTE =
  "反馈只记录操作、参数路径与分数，不保存照片、指令原文或任何文字备注。";

export const FEEDBACK_NOT_QUALITY_NOTE =
  "接受、拒绝与评分只是主观偏好记录，不代表方案在客观质量上更优。";
