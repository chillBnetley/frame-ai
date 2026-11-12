import type {
  AnalysisColor,
  AnalysisComposition,
  AnalysisIssue,
  AnalysisLighting,
  AnalysisRecommendation,
  AnalysisScene,
  AnalysisSubject,
  IssueSeverity,
  RecommendationPriority,
  TaskStage,
  TaskStatus,
} from "@/types/analysis";

const SCENE_LABELS: Record<AnalysisScene["primary"], string> = {
  portrait: "人像",
  landscape: "风光",
  street: "街拍",
  architecture: "建筑",
  night: "夜景",
  indoor: "室内",
  food: "美食",
  nature: "自然",
  other: "其他",
};

const SUBJECT_TYPE_LABELS: Record<AnalysisSubject["type"], string> = {
  person: "人物",
  building: "建筑",
  sky: "天空",
  road: "道路",
  plant: "植物",
  animal: "动物",
  food: "食物",
  vehicle: "交通工具",
  other: "其他",
};

const SUBJECT_ROLE_LABELS: Record<AnalysisSubject["role"], string> = {
  primary: "主要主体",
  secondary: "次要主体",
};

const LIGHTING_DIRECTION_LABELS: Record<AnalysisLighting["direction"], string> = {
  front: "顺光",
  side: "侧光",
  back: "逆光",
  side_back: "侧逆光",
  diffuse: "漫射光",
  overcast: "阴天光",
  artificial: "人工光",
  mixed: "混合光",
  unknown: "未知",
};

const LIGHTING_TYPE_LABELS: Record<AnalysisLighting["type"], string> = {
  natural: "自然光",
  artificial: "人工光",
  mixed: "混合光",
  unknown: "未知",
};

const CONTRAST_LABELS: Record<AnalysisLighting["contrast"], string> = {
  low: "低",
  moderate: "中等",
  high: "高",
  unknown: "未知",
};

const TEMPERATURE_LABELS: Record<AnalysisColor["temperature"], string> = {
  warm: "暖色",
  neutral: "中性",
  cool: "冷色",
  unknown: "未知",
};

const SATURATION_LABELS: Record<AnalysisColor["saturation"], string> = {
  low: "低饱和",
  moderate: "中等饱和",
  high: "高饱和",
  unknown: "未知",
};

const HARMONY_LABELS: Record<AnalysisColor["harmony"], string> = {
  harmonious: "协调",
  moderate: "一般",
  clashing: "冲突",
  unknown: "未知",
};

const BALANCE_LABELS: Record<AnalysisComposition["balance"], string> = {
  balanced: "均衡",
  moderate: "一般",
  unbalanced: "失衡",
  unknown: "未知",
};

const NEGATIVE_SPACE_LABELS: Record<AnalysisComposition["negativeSpace"], string> = {
  low: "偏少",
  moderate: "适中",
  high: "偏多",
  unknown: "未知",
};

const OCCLUSION_LABELS: Record<AnalysisComposition["occlusion"], string> = {
  none: "无遮挡",
  minor: "轻微遮挡",
  significant: "明显遮挡",
  unknown: "未知",
};

const SUBJECT_POSITION_LABELS: Record<
  AnalysisComposition["subjectPosition"],
  string
> = {
  left: "偏左",
  right: "偏右",
  center: "中央",
  top: "偏上",
  bottom: "偏下",
  unknown: "未知",
};

const ISSUE_TYPE_LABELS: Record<AnalysisIssue["type"], string> = {
  overexposure: "整体过曝",
  underexposure: "整体欠曝",
  highlight_clipping: "高光裁切",
  shadow_clipping: "暗部裁切",
  subject_underexposure: "主体欠曝",
  background_overexposure: "背景过曝",
  color_cast: "色偏",
  temperature_mismatch: "色温不匹配",
  saturation_issue: "饱和度问题",
  color_hierarchy_issue: "色彩层次问题",
  subject_placement: "主体位置",
  balance_issue: "画面失衡",
  negative_space_issue: "负空间不足",
  horizon_tilt: "地平线倾斜",
  focus_issue: "对焦问题",
  motion_blur: "动态模糊",
  high_noise: "噪点偏高",
  low_detail: "细节不足",
  harsh_contrast: "反差过强",
  flat_lighting: "光线平淡",
};

const CATEGORY_LABELS: Record<AnalysisRecommendation["category"], string> = {
  exposure: "曝光",
  color: "色彩",
  composition: "构图",
  sharpness: "清晰度",
  lighting: "光线",
};

export const SEVERITY_LABELS: Record<IssueSeverity, string> = {
  high: "高",
  medium: "中",
  low: "低",
};

export const PRIORITY_LABELS: Record<RecommendationPriority, string> = {
  high: "高优先级",
  medium: "中优先级",
  low: "低优先级",
};

const SEVERITY_ORDER: Record<IssueSeverity, number> = {
  high: 0,
  medium: 1,
  low: 2,
};

const PRIORITY_ORDER: Record<RecommendationPriority, number> = {
  high: 0,
  medium: 1,
  low: 2,
};

const STAGE_LABELS: Record<TaskStage, string> = {
  queued: "等待分析",
  preprocessing: "正在准备图片",
  vision: "正在理解照片并识别场景",
  features: "正在分析光线和色彩",
  diagnosis: "正在生成摄影诊断",
  completed: "分析完成",
  failed: "分析失败",
};

export interface AnalysisStageStep {
  stage: Exclude<TaskStage, "queued" | "completed" | "failed">;
  label: string;
}

/**
 * The backend reports these four real processing stages. The UI advances one
 * step per reported stage instead of inventing a percentage the provider does
 * not expose.
 */
export const ANALYSIS_STAGE_STEPS: readonly AnalysisStageStep[] = [
  { stage: "preprocessing", label: "准备图片" },
  { stage: "vision", label: "识别场景与主体" },
  { stage: "features", label: "分析光线与色彩" },
  { stage: "diagnosis", label: "生成摄影诊断" },
];

export function analysisActiveStep(
  status: TaskStatus | null,
  stage: TaskStage | null,
): number {
  if (status === "completed" || stage === "completed") {
    return ANALYSIS_STAGE_STEPS.length;
  }
  if (!stage || stage === "queued" || stage === "failed") {
    return 0;
  }
  const index = ANALYSIS_STAGE_STEPS.findIndex((step) => step.stage === stage);
  return index < 0 ? 0 : index;
}

export function analysisElapsedSeconds(
  startedAt: number | null,
  now: number,
): number {
  if (startedAt === null) {
    return 0;
  }
  return Math.max(0, Math.floor((now - startedAt) / 1000));
}

export function formatAnalysisElapsed(seconds: number): string {
  if (seconds < 60) {
    return `${seconds} 秒`;
  }
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest === 0 ? `${minutes} 分` : `${minutes} 分 ${rest} 秒`;
}

export function analysisSlowHint(seconds: number): string | null {
  if (seconds >= 60) {
    return "仍在等待模型返回。分析完成后结果会自动出现，你可以继续编辑或导出。";
  }
  if (seconds >= 30) {
    return "模型响应比平时慢，仍在不间断处理，可以继续编辑。";
  }
  return null;
}

export function describeAnalysisStage(
  status: TaskStatus | null,
  stage: TaskStage | null,
): string {
  if (status === "completed") {
    return "分析完成";
  }
  if (status === "failed") {
    return "分析失败";
  }
  if (status === "pending" || stage === "queued") {
    return "等待分析";
  }
  return stage ? STAGE_LABELS[stage] : "分析状态未知";
}

export function isRunningStatus(status: TaskStatus | null): boolean {
  return status === "pending" || status === "processing";
}

export function sceneLabel(value: AnalysisScene["primary"]): string {
  return SCENE_LABELS[value] ?? "其他";
}

export function subjectTypeLabel(value: AnalysisSubject["type"]): string {
  return SUBJECT_TYPE_LABELS[value] ?? "其他";
}

export function subjectRoleLabel(value: AnalysisSubject["role"]): string {
  return SUBJECT_ROLE_LABELS[value] ?? "主体";
}

export function lightingDirectionLabel(
  value: AnalysisLighting["direction"],
): string {
  return LIGHTING_DIRECTION_LABELS[value] ?? "未知";
}

export function lightingTypeLabel(value: AnalysisLighting["type"]): string {
  return LIGHTING_TYPE_LABELS[value] ?? "未知";
}

export function contrastLabel(value: AnalysisLighting["contrast"]): string {
  return CONTRAST_LABELS[value] ?? "未知";
}

export function temperatureLabel(value: AnalysisColor["temperature"]): string {
  return TEMPERATURE_LABELS[value] ?? "未知";
}

export function saturationLabel(value: AnalysisColor["saturation"]): string {
  return SATURATION_LABELS[value] ?? "未知";
}

export function harmonyLabel(value: AnalysisColor["harmony"]): string {
  return HARMONY_LABELS[value] ?? "未知";
}

export function balanceLabel(value: AnalysisComposition["balance"]): string {
  return BALANCE_LABELS[value] ?? "未知";
}

export function negativeSpaceLabel(
  value: AnalysisComposition["negativeSpace"],
): string {
  return NEGATIVE_SPACE_LABELS[value] ?? "未知";
}

export function occlusionLabel(value: AnalysisComposition["occlusion"]): string {
  return OCCLUSION_LABELS[value] ?? "未知";
}

export function subjectPositionLabel(
  value: AnalysisComposition["subjectPosition"],
): string {
  return SUBJECT_POSITION_LABELS[value] ?? "未知";
}

export function issueTypeLabel(value: AnalysisIssue["type"]): string {
  return ISSUE_TYPE_LABELS[value] ?? "其他问题";
}

export function categoryLabel(
  value: AnalysisRecommendation["category"],
): string {
  return CATEGORY_LABELS[value] ?? "其他";
}

export function sortIssues(issues: readonly AnalysisIssue[]): AnalysisIssue[] {
  return [...issues].sort(
    (left, right) =>
      SEVERITY_ORDER[left.severity] - SEVERITY_ORDER[right.severity] ||
      right.confidence - left.confidence ||
      left.id.localeCompare(right.id),
  );
}

export function sortRecommendations(
  recommendations: readonly AnalysisRecommendation[],
): AnalysisRecommendation[] {
  return [...recommendations].sort(
    (left, right) =>
      PRIORITY_ORDER[left.priority] - PRIORITY_ORDER[right.priority] ||
      left.category.localeCompare(right.category) ||
      left.description.localeCompare(right.description),
  );
}

export function relatedIssueLabels(
  recommendation: AnalysisRecommendation,
  issues: readonly AnalysisIssue[],
): string[] {
  if (recommendation.targetRegions.length === 0) {
    return [];
  }
  const targets = new Set(recommendation.targetRegions);
  const labels: string[] = [];
  for (const issue of issues) {
    if (issue.regionIds.some((regionId) => targets.has(regionId))) {
      const label = issueTypeLabel(issue.type);
      if (!labels.includes(label)) {
        labels.push(label);
      }
    }
  }
  return labels;
}