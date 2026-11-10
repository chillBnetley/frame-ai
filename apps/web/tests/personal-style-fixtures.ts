import type {
  CustomStyleParseResponse,
  CustomStyleRefineResponse,
  ImageListResponse,
  PersonalStyleAnalysisResponse,
  PersonalStyleCompareResponse,
  PersonalStyleDetailResponse,
  PersonalStyleFusionResponse,
  PersonalStyleItem,
  PersonalStyleProfile,
  PersonalStyleReference,
  PersonalStyleVersionListResponse,
  PhotoVisualFeatures,
  StyleAuthoringDraft,
} from "@/types/personal-style";

export const PERSONAL_STYLE_ID = "personal_abcdef123456";
export const PERSONAL_IMAGE_ID = "11111111-1111-4111-8111-111111111111";
export const PERSONAL_REFERENCE_ID = "22222222-2222-4222-8222-222222222222";
export const PERSONAL_IMAGE_ID_2 = "33333333-3333-4333-8333-333333333333";
export const PERSONAL_REFERENCE_ID_2 = "44444444-4444-4444-8444-444444444444";

const CREATED_AT = "2026-11-09T10:00:00Z";
const UPDATED_AT = "2026-11-10T08:00:00Z";

export function personalStyleProfile(
  overrides: Partial<PersonalStyleProfile> = {},
): PersonalStyleProfile {
  return {
    id: PERSONAL_STYLE_ID,
    kind: "personal",
    version: "1.1",
    name: "克制的城市叙事",
    description: "低饱和、偏冷的环境色彩，保留暗部层次与自然街头质感。",
    philosophy: "从参考照片中提取稳定的个人审美，而不是套用固定滤镜。",
    color: {
      tendency: "整体偏冷，低饱和",
      relationships: "色彩关系自然",
      saturation: "低饱和",
    },
    light: {
      contrast: "中等反差",
      shadows: "暗部层次自然",
      highlights: "高光柔和受控",
      expression: "柔和漫射光，侧光",
    },
    composition: {
      space: "负空间适中",
      geometry: "构图平衡较为平衡",
      negativeSpace: "负空间适中",
      subjectRelation: "主体多位于画面中央",
    },
    texture: {
      grain: "颗粒克制",
      sharpness: "清晰度自然",
      detail: "细节保留自然",
    },
    sceneFit: {
      suitable: ["street", "architecture"],
      suitableNotes: "参考照片覆盖街拍、建筑。",
      unsuitableNotes: "未覆盖场景需要重新适配。",
    },
    postStrategy: "保持低饱和与偏冷环境色，避免过度压暗。",
    captureTechniques: "用户提供的参考照片。",
    constraints: ["preserve_skin_tone", "preserve_highlight_detail"],
    preserveNotes: "保护肤色与高光细节。",
    sources: [
      {
        title: "个人参考照片分析（5 张）",
        url: null,
        license: "用户主动授权，不用于模型训练",
      },
    ],
    engineStyle: "street",
    envelope: {
      exposureEv: 1,
      contrast: 25,
      highlights: 25,
      shadows: 25,
      whites: 20,
      blacks: 20,
      temperature: 15,
      tint: 10,
      saturation: 25,
      vibrance: 20,
      clarity: 20,
      denoise: 25,
      vignette: 20,
      grain: 15,
    },
    defaultStrength: 0.57,
    enabled: true,
    personal: {
      schemaVersion: "personal/1",
      source: "photos",
      confidence: 0.62,
      stability: {
        color: 0.9,
        tone: 0.82,
        light: 0.9,
        texture: 0.88,
        scene: 0.6,
      },
      targets: { saturation: -9.6, temperature: -6, contrast: -4 },
      sceneTargets: {},
      protected: ["preserve_skin_tone", "preserve_highlight_detail"],
      avoid: ["oversaturated"],
      userOverrides: [],
      sampleCount: 5,
      anomalyCount: 0,
    },
    ...overrides,
  };
}

export function personalStyleReference(
  overrides: Partial<PersonalStyleReference> = {},
): PersonalStyleReference {
  return {
    id: PERSONAL_REFERENCE_ID,
    imageId: PERSONAL_IMAGE_ID,
    imageSha256: "a".repeat(64),
    originalName: "street.png",
    status: "active",
    consentScope: "analysis_only",
    consentAt: CREATED_AT,
    addedAt: CREATED_AT,
    analysisId: null,
    ...overrides,
  };
}

export function personalStyleItem(
  overrides: Partial<PersonalStyleItem> = {},
): PersonalStyleItem {
  return {
    id: PERSONAL_STYLE_ID,
    name: "克制的城市叙事",
    description: "低饱和、偏冷的环境色彩，保留暗部层次与自然街头质感。",
    source: "photos",
    status: "draft",
    version: "1.1",
    favorite: false,
    confidence: 0.62,
    sampleCount: 5,
    referenceCount: 5,
    updatedAt: UPDATED_AT,
    ...overrides,
  };
}

export function personalStyleDetail(
  overrides: Partial<PersonalStyleDetailResponse> = {},
): PersonalStyleDetailResponse {
  return {
    style: personalStyleProfile(),
    definition: {
      schemaVersion: "personal-definition/1",
      userOverrides: {},
      note: null,
    },
    status: "draft",
    source: "photos",
    favorite: false,
    references: [personalStyleReference()],
    createdAt: CREATED_AT,
    updatedAt: UPDATED_AT,
    ...overrides,
  };
}

export function personalStyleAnalysis(
  overrides: Partial<PersonalStyleAnalysisResponse> = {},
): PersonalStyleAnalysisResponse {
  return {
    styleId: PERSONAL_STYLE_ID,
    references: [
      {
        referenceId: PERSONAL_REFERENCE_ID,
        imageId: PERSONAL_IMAGE_ID,
        status: "analysis_required",
        stage: null,
        analysisId: null,
        confidence: null,
        anomalyCount: 0,
        featureAvailable: false,
        error: null,
      },
    ],
    completedCount: 0,
    totalCount: 1,
    ...overrides,
  };
}

export function personalStyleAnalysisCompleted(): PersonalStyleAnalysisResponse {
  return personalStyleAnalysis({
    references: [
      {
        referenceId: PERSONAL_REFERENCE_ID,
        imageId: PERSONAL_IMAGE_ID,
        status: "completed",
        stage: "completed",
        analysisId: "55555555-5555-4555-8555-555555555555",
        confidence: 0.62,
        anomalyCount: 1,
        featureAvailable: true,
        error: null,
      },
    ],
    completedCount: 1,
  });
}

export function photoVisualFeatures(): PhotoVisualFeatures {
  return {
    schemaVersion: "visual-dna-photo/1",
    extractorVersion: "visual-dna/1",
    imageId: PERSONAL_IMAGE_ID,
    imageSha256: "a".repeat(64),
    analysisId: "55555555-5555-4555-8555-555555555555",
    analyzedAt: UPDATED_AT,
    isMock: true,
    overallConfidence: 0.47,
    scene: { primary: "street", secondary: [], confidence: 0.6 },
    color: {
      temperatureOffset: -0.12,
      tintOffset: 0,
      saturationMean: 0.2,
      saturationP10: 0.05,
      saturationP50: 0.18,
      saturationP90: 0.42,
      saturationP95: 0.5,
      colorConcentration: 0.4,
      dominantColors: ["#334455"],
      hueDistribution: [],
      harmony: "moderate",
      tendency: "cool",
      level: "low",
      monochrome: false,
      confidence: 0.6,
    },
    tone: {
      luminanceMean: 0.45,
      luminanceStd: 0.12,
      luminanceP5: 0.08,
      luminanceP50: 0.42,
      luminanceP95: 0.82,
      highlightsPct: 1.2,
      shadowsPct: 3.1,
      contrastStrength: 0.34,
      highKey: false,
      lowKey: false,
      lowLight: false,
      contrastLevel: "moderate",
    },
    light: {
      direction: "side",
      type: "natural",
      contrast: "moderate",
      softness: 0.5,
      directional: true,
      confidence: 0.6,
    },
    texture: {
      sharpness: 0.4,
      noise: 0.12,
      gradientAnisotropy: 0.2,
      grainTendency: 0.12,
      detailRetention: 0.4,
      confidence: 0.6,
    },
    composition: {
      balance: "moderate",
      subjectPosition: "center",
      negativeSpace: "moderate",
      occlusion: "none",
      subjectAreaRatio: null,
      horizonTiltDeg: null,
      edgeDensityGrid: [0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1],
      confidence: 0.6,
    },
    readings: [
      {
        category: "color",
        key: "castTemperature",
        label: "色温偏色",
        value: -12,
        normalized: -0.12,
        description: "色温偏色 -12.0（偏冷）。",
        evidence: ["measurement.color.cast.temperature"],
        confidence: 1,
        origin: "measurement",
        editable: false,
      },
      {
        category: "color",
        key: "saturationIntent",
        label: "色彩浓度倾向",
        value: "restrained",
        normalized: 0.2,
        description: "饱和度整体偏低，色彩表达倾向于克制。",
        evidence: ["measurement.color.saturationMean"],
        confidence: 1,
        origin: "derived",
        editable: true,
      },
    ],
    anomalies: [
      {
        code: "low_light_confidence",
        category: "light",
        severity: "warning",
        message: "光线判断置信度较低。",
        evidence: ["lighting.confidence"],
      },
    ],
    limitations: ["当前分析由模拟 Provider 生成，语义特征仅供占位。"],
  };
}

export function personalStyleFusion(): PersonalStyleFusionResponse {
  return {
    style: personalStyleProfile(),
    definition: {
      schemaVersion: "personal-definition/1",
      userOverrides: {},
      note: null,
    },
    version: "1.1",
    status: "draft",
    favorite: false,
    summary: "个人风格概览：整体偏冷，低饱和。\n影调：中等反差。",
    sections: [
      {
        key: "color",
        title: "色彩",
        description: "整体偏冷，低饱和。",
        evidence: ["80% 的照片支持偏冷"],
      },
      {
        key: "tone",
        title: "影调",
        description: "中等反差。",
        evidence: ["80% 的照片支持中等反差"],
      },
      {
        key: "light",
        title: "光线",
        description: "柔和漫射光。",
        evidence: ["80% 的照片支持柔和漫射光"],
      },
      {
        key: "texture",
        title: "质感",
        description: "自然质感。",
        evidence: ["80% 的照片支持自然质感"],
      },
      {
        key: "scene",
        title: "场景",
        description: "参考照片主要来自街拍。",
        evidence: ["街拍 1 张"],
      },
      {
        key: "constraints",
        title: "处理原则",
        description: "保护肤色；用户回避：避免过饱和。",
        evidence: ["保护肤色"],
      },
    ],
    conflicts: [],
    scenes: [
      {
        scene: "street",
        photoCount: 1,
        share: 1,
        confidence: 0.47,
        description: "低饱和、中等反差、柔和漫射光",
      },
    ],
    contributions: [
      {
        referenceId: PERSONAL_REFERENCE_ID,
        imageId: PERSONAL_IMAGE_ID,
        scene: "street",
        confidence: 0.47,
        weight: 0.28,
        anomalyCount: 1,
      },
    ],
    occasional: [],
    stability: {
      color: 0.9,
      tone: 0.82,
      light: 0.9,
      texture: 0.88,
      scene: 0.6,
    },
    confidence: 0.62,
    sampleCount: 1,
    anomalyCount: 0,
    defaultStrength: 0.57,
    limitations: ["参考照片少于 3 张，全局结论的置信度有限。"],
    createdAt: UPDATED_AT,
  };
}

export function personalStyleVersions(): PersonalStyleVersionListResponse {
  return {
    styleId: PERSONAL_STYLE_ID,
    versions: [
      {
        version: "1.1",
        changeSource: "analysis",
        changeNote: "融合 1 张参考照片",
        createdAt: UPDATED_AT,
      },
      {
        version: "1.0",
        changeSource: "user",
        changeNote: null,
        createdAt: CREATED_AT,
      },
    ],
  };
}

export function personalStyleCompare(): PersonalStyleCompareResponse {
  return {
    styleId: PERSONAL_STYLE_ID,
    fromVersion: "1.0",
    toVersion: "1.1",
    changes: [
      {
        path: "profile.name",
        before: "城市",
        after: "克制的城市叙事",
      },
      {
        path: "profile.personal.confidence",
        before: 0,
        after: 0.62,
      },
    ],
  };
}

export function styleAuthoringDraft(
  overrides: Partial<StyleAuthoringDraft> = {},
): StyleAuthoringDraft {
  return {
    name: "克制的城市叙事",
    description: "低饱和、偏冷的环境色，保留暗部层次与自然肤色。",
    color: {
      tendency: "整体偏冷，低饱和",
      relationships: "环境色自然，主色与辅助色关系克制",
      saturation: "低饱和",
    },
    light: {
      contrast: "中等反差",
      shadows: "保留暗部层次",
      highlights: "高光柔和",
      expression: "自然光优先",
    },
    composition: {
      space: "负空间适中",
      geometry: "平衡构图",
      negativeSpace: "适中",
      subjectRelation: "主体与环境保护克制关系",
    },
    texture: {
      grain: "颗粒克制",
      sharpness: "清晰度自然",
      detail: "细节自然",
    },
    suitableScenes: ["street", "portrait"],
    unsuitableNotes: "未覆盖场景需要重新适配。",
    targets: { saturation: -12, temperature: -8 },
    protected: ["preserve_skin_tone", "preserve_highlight_detail"],
    avoid: ["oversaturated"],
    summary: "色彩：整体偏冷，低饱和；影调：中等反差；光线：自然光优先。",
    rationale: ["识别到低饱和或克制的色彩倾向。", "识别到肤色保护需求。"],
    warnings: [],
    limitations: ["模拟数据：自然语言风格由关键词规则解析。"],
    confidence: 0.55,
    ...overrides,
  };
}

export function customParseResponse(): CustomStyleParseResponse {
  return {
    draft: styleAuthoringDraft(),
    provider: {
      name: "mock",
      model: "mock-planner",
      promptVersion: "stage6.2-style-authoring/1",
      isMock: true,
    },
  };
}

export function customRefineResponse(): CustomStyleRefineResponse {
  return {
    styleId: PERSONAL_STYLE_ID,
    currentVersion: "1.0",
    draft: styleAuthoringDraft({
      targets: {
        saturation: -16,
        temperature: -6,
        highlights: -4,
        shadows: 4,
      },
      light: {
        contrast: "中等反差",
        shadows: "保留更多暗部层次",
        highlights: "保留更多高光细节",
        expression: "自然光优先",
      },
      protected: [
        "preserve_skin_tone",
        "preserve_highlight_detail",
        "preserve_shadow_detail",
      ],
    }),
    provider: {
      name: "mock",
      model: "mock-planner",
      promptVersion: "stage6.2-style-authoring/1",
      isMock: true,
    },
  };
}

export function imageLibrary(): ImageListResponse {
  return {
    images: [
      {
        id: PERSONAL_IMAGE_ID,
        originalName: "street.png",
        width: 96,
        height: 64,
        mimeType: "image/png",
        bytes: 128,
        createdAt: CREATED_AT,
      },
      {
        id: PERSONAL_IMAGE_ID_2,
        originalName: "brick.png",
        width: 96,
        height: 64,
        mimeType: "image/png",
        bytes: 128,
        createdAt: CREATED_AT,
      },
    ],
    nextOffset: null,
  };
}
