import { describe, expect, it } from "vitest";

import {
  ANALYSIS_STAGE_STEPS,
  analysisActiveStep,
  analysisElapsedSeconds,
  analysisSlowHint,
  balanceLabel,
  describeAnalysisStage,
  formatAnalysisElapsed,
  harmonyLabel,
  negativeSpaceLabel,
  occlusionLabel,
  relatedIssueLabels,
  sortIssues,
  sortRecommendations,
  subjectPositionLabel,
} from "@/features/analysis/presentation";
import { analysisReport } from "./analysis-fixtures";

describe("analysis presentation", () => {
  it.each([
    ["pending", "queued", "等待分析"],
    ["processing", "preprocessing", "正在准备图片"],
    ["processing", "vision", "正在理解照片并识别场景"],
    ["processing", "features", "正在分析光线和色彩"],
    ["processing", "diagnosis", "正在生成摄影诊断"],
    ["completed", "completed", "分析完成"],
    ["failed", "failed", "分析失败"],
  ] as const)("maps %s/%s to the visible stage label", (status, stage, label) => {
    expect(describeAnalysisStage(status, stage)).toBe(label);
  });

  it("sorts issues by severity then confidence", () => {
    const issues = analysisReport().issues;
    const sorted = sortIssues(issues);
    expect(sorted.map((issue) => issue.severity)).toEqual(["high", "low"]);
  });

  it("sorts recommendations by priority", () => {
    const recommendations = analysisReport().recommendations;
    const sorted = sortRecommendations(recommendations);
    expect(sorted.map((recommendation) => recommendation.priority)).toEqual([
      "high",
      "low",
    ]);
  });

  it("links recommendations to issues sharing target regions", () => {
    const report = analysisReport();
    const high = report.recommendations.find(
      (recommendation) => recommendation.priority === "high",
    );
    expect(high).toBeDefined();
    expect(relatedIssueLabels(high!, report.issues)).toEqual(["整体欠曝"]);
  });

  it("returns no related issue labels for whole-frame recommendations", () => {
    expect(
      relatedIssueLabels(
        {
          category: "composition",
          priority: "low",
          description: "调整取景。",
          targetRegions: [],
        },
        analysisReport().issues,
      ),
    ).toEqual([]);
  });

  it.each([
    ["harmonious", "协调"],
    ["moderate", "一般"],
    ["clashing", "冲突"],
    ["unknown", "未知"],
  ] as const)("maps color harmony %s to a label", (value, label) => {
    expect(harmonyLabel(value)).toBe(label);
  });

  it.each([
    ["balanced", "均衡"],
    ["moderate", "一般"],
    ["unbalanced", "失衡"],
    ["unknown", "未知"],
  ] as const)("maps composition balance %s to a label", (value, label) => {
    expect(balanceLabel(value)).toBe(label);
  });

  it.each([
    ["low", "偏少"],
    ["moderate", "适中"],
    ["high", "偏多"],
    ["unknown", "未知"],
  ] as const)("maps negative space %s to a label", (value, label) => {
    expect(negativeSpaceLabel(value)).toBe(label);
  });

  it.each([
    ["none", "无遮挡"],
    ["minor", "轻微遮挡"],
    ["significant", "明显遮挡"],
    ["unknown", "未知"],
  ] as const)("maps occlusion %s to a label", (value, label) => {
    expect(occlusionLabel(value)).toBe(label);
  });

  it.each([
    ["left", "偏左"],
    ["right", "偏右"],
    ["center", "中央"],
    ["top", "偏上"],
    ["bottom", "偏下"],
    ["unknown", "未知"],
  ] as const)("maps subject position %s to a label", (value, label) => {
    expect(subjectPositionLabel(value)).toBe(label);
  });
});

describe("analysis progress presentation", () => {
  it("maps backend stages onto four ordered steps", () => {
    expect(ANALYSIS_STAGE_STEPS.map((step) => step.stage)).toEqual([
      "preprocessing",
      "vision",
      "features",
      "diagnosis",
    ]);
  });

  it.each([
    [null, null, 0],
    ["pending", "queued", 0],
    ["processing", "preprocessing", 0],
    ["processing", "vision", 1],
    ["processing", "features", 2],
    ["processing", "diagnosis", 3],
    ["completed", "completed", 4],
  ] as const)(
    "maps status %s and stage %s to step %s",
    (status, stage, step) => {
      expect(analysisActiveStep(status, stage)).toBe(step);
    },
  );

  it("never reports negative elapsed time", () => {
    expect(analysisElapsedSeconds(null, 1_000)).toBe(0);
    expect(analysisElapsedSeconds(2_000, 1_000)).toBe(0);
    expect(analysisElapsedSeconds(1_000, 6_500)).toBe(5);
  });

  it("formats elapsed time with minutes for long runs", () => {
    expect(formatAnalysisElapsed(0)).toBe("0 秒");
    expect(formatAnalysisElapsed(59)).toBe("59 秒");
    expect(formatAnalysisElapsed(60)).toBe("1 分");
    expect(formatAnalysisElapsed(95)).toBe("1 分 35 秒");
  });

  it("adds a reassurance hint only after a slow run", () => {
    expect(analysisSlowHint(29)).toBeNull();
    expect(analysisSlowHint(30)).toContain("比平时慢");
    expect(analysisSlowHint(60)).toContain("仍在等待模型返回");
  });
});