import type {
  ConversionMode,
  FitDimension,
  FitLevel,
  SceneLabel,
  StyleKind,
  StyleLibraryItem,
} from "@/types/style-library";

export const SCENE_LABELS: Record<SceneLabel, string> = {
  portrait: "人像",
  landscape: "风光",
  street: "街头",
  architecture: "建筑",
  night: "夜景",
  indoor: "室内",
  food: "美食",
  nature: "自然",
  other: "其他",
};

export const STYLE_KIND_LABELS: Record<StyleKind, string> = {
  master: "大师",
  genre: "流派",
};

export const FIT_LEVEL_LABELS: Record<FitLevel, string> = {
  high: "高度适配",
  medium: "较为适合",
  low: "需要调整",
  unsuitable: "不太适合",
};

export const FIT_DIMENSION_LABELS: Record<FitDimension, string> = {
  color: "色彩",
  light: "光线",
  scene: "场景",
  composition: "构图",
  subject: "主体",
};

export const CONVERSION_MODE_LABELS: Record<ConversionMode, string> = {
  natural: "Natural 真实优先",
  style: "Style 风格优先",
  creative: "Creative 创意优先",
};

export function sceneLabel(scene: SceneLabel): string {
  return SCENE_LABELS[scene] ?? scene;
}

export function styleScenes(style: StyleLibraryItem): string {
  return style.suitableScenes.map(sceneLabel).join(" · ");
}

export function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleDateString("zh-CN", { month: "short", day: "numeric" });
}

export function styleGradient(styleId: string, kind: StyleKind): string {
  let hash = 0;
  for (let index = 0; index < styleId.length; index += 1) {
    hash = (hash * 31 + styleId.charCodeAt(index)) % 360;
  }
  const base = kind === "master" ? 205 : 158;
  const hue = (base + hash) % 360;
  return [
    `radial-gradient(circle at 28% 22%, hsl(${hue} 36% 72% / 0.9), transparent 58%)`,
    `radial-gradient(circle at 74% 68%, hsl(${(hue + 34) % 360} 30% 48% / 0.8), transparent 62%)`,
    `linear-gradient(135deg, hsl(${(hue + 210) % 360} 24% 20%), hsl(${(hue + 190) % 360} 18% 34%))`,
  ].join(", ");
}

export function styleAccent(styleId: string, kind: StyleKind): string {
  let hash = 0;
  for (let index = 0; index < styleId.length; index += 1) {
    hash = (hash * 17 + styleId.charCodeAt(index)) % 360;
  }
  return `hsl(${(kind === "master" ? 202 : 158) + hash} 32% 42%)`;
}
