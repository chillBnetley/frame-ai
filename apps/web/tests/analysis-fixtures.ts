import type {
  AnalysisReport,
  AnalysisStatusResponse,
} from "@/types/analysis";
import { IMAGE_ID } from "./session-fixtures";

export const ANALYSIS_ID = "66666666-6666-4666-8666-666666666666";
export const ANALYSIS_OTHER_IMAGE_ID =
  "77777777-7777-4777-8777-777777777777";

export function analysisReport(
  overrides: Partial<AnalysisReport> = {},
): AnalysisReport {
  return {
    analysisId: ANALYSIS_ID,
    schemaVersion: "stage3/1",
    status: "completed",
    image: {
      id: IMAGE_ID,
      width: 1600,
      height: 1200,
      aspectRatio: 4 / 3,
      sha256: "a".repeat(64),
    },
    engine: {
      visionProvider: "mock",
      visionModel: "mock-vision",
      decisionProvider: "mock",
      decisionModel: "mock-decision",
      promptVersion: "mock/1",
      analyzerVersion: "test",
      isMock: true,
    },
    scene: {
      primary: "portrait",
      secondary: ["indoor"],
      confidence: 0.72,
    },
    subjects: [
      {
        id: "subject_001",
        type: "person",
        role: "primary",
        confidence: 0.8,
        bbox: { x: 0.2, y: 0.1, width: 0.4, height: 0.7 },
        regionId: "region_001",
      },
      {
        id: "subject_002",
        type: "plant",
        role: "secondary",
        confidence: 0.6,
        bbox: { x: 0.7, y: 0.4, width: 0.2, height: 0.3 },
        regionId: "region_002",
      },
    ],
    regions: [
      {
        id: "region_001",
        type: "person",
        source: "vision",
        confidence: 0.8,
        bbox: { x: 0.2, y: 0.1, width: 0.4, height: 0.7 },
        mask: null,
      },
      {
        id: "region_002",
        type: "plant",
        source: "vision",
        confidence: 0.6,
        bbox: { x: 0.7, y: 0.4, width: 0.2, height: 0.3 },
        mask: null,
      },
    ],
    lighting: {
      direction: "side",
      type: "natural",
      contrast: "moderate",
      confidence: 0.6,
    },
    color: {
      temperature: "warm",
      saturation: "moderate",
      harmony: "harmonious",
      dominantColors: ["#C58B6A"],
      confidence: 0.55,
    },
    composition: {
      balance: "balanced",
      subjectPosition: "center",
      negativeSpace: "moderate",
      occlusion: "none",
      subjectAreaRatio: 0.28,
      horizonTiltDeg: 1.2,
      confidence: 0.5,
    },
    technicalQuality: {
      exposure: "slightly_underexposed",
      sharpness: "good",
      noise: "low",
      confidence: 0.6,
    },
    measurements: {
      luminance: {
        mean: 0.45,
        std: 0.18,
        p1: 0.05,
        p5: 0.12,
        p50: 0.44,
        p95: 0.9,
        p99: 0.98,
        histogram32: Array.from({ length: 32 }, () => 0.03125),
      },
      clipping: { highlightsPct: 1.5, shadowsPct: 2.5 },
      color: {
        meanRgb: [0.17, 0.18, 0.2],
        cast: { temperature: 0.02, tint: -0.01 },
        saturationMean: 0.35,
        saturationP95: 0.62,
        saturationP10: 0.12,
        saturationP50: 0.34,
        saturationP90: 0.58,
        colorConcentration: 0.55,
        rgbHistogram: Array.from({ length: 3 }, () =>
          Array.from({ length: 32 }, () => 0.03125),
        ),
        hsvHistogram: [
          Array.from({ length: 16 }, () => 0.0625),
          Array.from({ length: 8 }, () => 0.125),
          Array.from({ length: 8 }, () => 0.125),
        ],
      },
      detail: {
        sharpness: 0.3,
        noiseEstimate: 0.12,
        gradientAnisotropy: 0.2,
      },
      composition: {
        edgeDensityGrid3x3: Array.from({ length: 9 }, () => 0.1),
        brightnessCentroid: [0.51, 0.48],
        horizonTiltDeg: 1.2,
      },
    },
    issues: [
      {
        id: "c_highlight_clipping",
        type: "highlight_clipping",
        severity: "low",
        confidence: 0.6,
        evidence: "高光裁切比例为 1.5%。",
        suggestion: "降低曝光或使用高光恢复，优先保留亮部纹理。",
        regionIds: ["region_002"],
      },
      {
        id: "c_underexposure",
        type: "underexposure",
        severity: "high",
        confidence: 0.9,
        evidence: "中位亮度 0.12，低于阈值 0.18。",
        suggestion: "提高整体曝光或针对暗部做适度提亮。",
        regionIds: ["region_001"],
      },
    ],
    recommendations: [
      {
        category: "exposure",
        priority: "low",
        description: "适当提高整体曝光，并留意暗部细节。",
        targetRegions: ["region_002"],
      },
      {
        category: "lighting",
        priority: "high",
        description: "调整拍摄角度，避免主体处于阴影中。",
        targetRegions: ["region_001"],
      },
    ],
    limitations: ["仅依据给定测量与候选问题。"],
    createdAt: "2026-11-03T00:00:00Z",
    completedAt: "2026-11-03T00:00:05Z",
    ...overrides,
  };
}

export function analysisStatus(
  overrides: Partial<AnalysisStatusResponse> = {},
): AnalysisStatusResponse {
  return {
    analysisId: ANALYSIS_ID,
    status: "pending",
    stage: "queued",
    isMock: true,
    resultAvailable: false,
    error: null,
    createdAt: "2026-11-03T00:00:00Z",
    updatedAt: "2026-11-03T00:00:00Z",
    startedAt: null,
    completedAt: null,
    result: null,
    ...overrides,
  };
}