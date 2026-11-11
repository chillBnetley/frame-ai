import { describe, expect, it } from "vitest";

import { buildGenerativeSuggestions } from "@/features/generative/suggestions";
import type { AnalysisIssue } from "@/types/analysis";
import { analysisReport } from "./analysis-fixtures";

function issue(overrides: Partial<AnalysisIssue> & { id: string }): AnalysisIssue {
  return {
    type: "low_detail",
    severity: "medium",
    confidence: 0.8,
    evidence: "证据",
    suggestion: null,
    regionIds: [],
    ...overrides,
  };
}

describe("buildGenerativeSuggestions", () => {
  it("returns nothing without a report", () => {
    expect(buildGenerativeSuggestions(null)).toEqual([]);
  });

  it("keeps exposure and colour defects in 参数精修", () => {
    const report = analysisReport({
      issues: [
        issue({ id: "a", type: "overexposure" }),
        issue({ id: "b", type: "color_cast" }),
        issue({ id: "c", type: "saturation_issue" }),
        issue({ id: "d", type: "high_noise" }),
        issue({ id: "e", type: "horizon_tilt" }),
      ],
    });

    const suggestions = buildGenerativeSuggestions(report);

    expect(suggestions).toHaveLength(5);
    for (const suggestion of suggestions) {
      expect(suggestion.route).toBe("adjustment");
      expect(suggestion.capability).toBeNull();
      expect(suggestion.instruction).toBeNull();
    }
  });

  it("routes composition defects to outpainting", () => {
    const report = analysisReport({
      issues: [
        issue({ id: "a", type: "negative_space_issue" }),
        issue({ id: "b", type: "subject_placement" }),
        issue({ id: "c", type: "balance_issue" }),
      ],
    });

    const suggestions = buildGenerativeSuggestions(report);

    expect(suggestions.map((item) => item.capability)).toEqual([
      "outpaint",
      "outpaint",
      "outpaint",
    ]);
    for (const suggestion of suggestions) {
      expect(suggestion.route).toBe("generative");
      expect(suggestion.instruction).toBeTruthy();
      expect(suggestion.instruction?.length).toBeLessThanOrEqual(2000);
    }
  });

  it("routes detail defects to local editing and attaches the matched subject box", () => {
    const report = analysisReport({
      issues: [
        issue({ id: "a", type: "low_detail", regionIds: ["region_002"] }),
        issue({ id: "b", type: "focus_issue", regionIds: ["region_001"] }),
        issue({ id: "c", type: "motion_blur", regionIds: ["region_001"] }),
      ],
    });

    const suggestions = buildGenerativeSuggestions(report);

    expect(suggestions.map((item) => item.capability)).toEqual([
      "local_edit",
      "local_edit",
      "local_edit",
    ]);
    expect(suggestions[0].subjectBbox).toEqual({ x: 0.7, y: 0.4, width: 0.2, height: 0.3 });
    expect(suggestions[1].subjectLabel).toBe("人物");
    expect(suggestions[1].subjectBbox).toEqual({ x: 0.2, y: 0.1, width: 0.4, height: 0.7 });
  });

  it("leaves the subject box empty when no region matches", () => {
    const report = analysisReport({
      issues: [issue({ id: "a", type: "low_detail", regionIds: ["region_999"] })],
    });

    const [suggestion] = buildGenerativeSuggestions(report);

    expect(suggestion.subjectBbox).toBeNull();
    expect(suggestion.subjectLabel).toBeNull();
  });

  it("prefers the primary subject when several regions match", () => {
    const report = analysisReport({
      issues: [
        issue({ id: "a", type: "low_detail", regionIds: ["region_001", "region_002"] }),
      ],
    });

    const [suggestion] = buildGenerativeSuggestions(report);

    expect(suggestion.subjectLabel).toBe("人物");
  });

  it("lists generative suggestions first, ordered by severity", () => {
    const report = analysisReport({
      issues: [
        issue({ id: "low", type: "underexposure", severity: "high" }),
        issue({ id: "gen-low", type: "low_detail", severity: "low" }),
        issue({ id: "gen-high", type: "balance_issue", severity: "high" }),
        issue({ id: "gen-medium", type: "focus_issue", severity: "medium" }),
      ],
    });

    expect(buildGenerativeSuggestions(report).map((item) => item.id)).toEqual([
      "gen-high",
      "gen-medium",
      "gen-low",
      "low",
    ]);
  });

  it("carries the backend advice for adjustment suggestions", () => {
    const report = analysisReport({
      issues: [
        issue({
          id: "a",
          type: "underexposure",
          evidence: "中位亮度 0.12。",
          suggestion: "提高整体曝光。",
        }),
      ],
    });

    const [suggestion] = buildGenerativeSuggestions(report);

    expect(suggestion.advice).toBe("提高整体曝光。");
    expect(suggestion.evidence).toBe("中位亮度 0.12。");
    expect(suggestion.label).toBe("整体欠曝");
  });

  it("never suggests removal, which needs an explicit user-marked object", () => {
    const report = analysisReport();

    expect(
      buildGenerativeSuggestions(report).some((item) => item.capability === "remove"),
    ).toBe(false);
  });
});