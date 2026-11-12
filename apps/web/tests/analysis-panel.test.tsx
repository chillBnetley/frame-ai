import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { describe, expect, it, vi } from "vitest";

import { AnalysisPanel } from "@/features/analysis/components/analysis-panel";
import type { UseAnalysisResult } from "@/features/analysis/hooks/use-analysis";
import { analysisReport, ANALYSIS_OTHER_IMAGE_ID } from "./analysis-fixtures";
import { IMAGE_ID } from "./session-fixtures";

function analysisState(
  overrides: Partial<UseAnalysisResult> = {},
): UseAnalysisResult {
  return {
    analysisId: null,
    status: null,
    stage: null,
    isMock: false,
    report: null,
    error: null,
    requestPending: false,
    startedAt: null,
    running: false,
    start: vi.fn(),
    retry: vi.fn(),
    rerun: vi.fn(),
    ...overrides,
  };
}

function renderPanel(state: UseAnalysisResult, onClose = vi.fn()) {
  const view = render(
    <AnalysisPanel
      open
      imageId={IMAGE_ID}
      analysis={state}
      onClose={onClose}
    />,
  );
  return { ...view, onClose };
}

describe("AnalysisPanel", () => {
  it("starts an analysis from the idle state", async () => {
    const state = analysisState();
    renderPanel(state);

    expect(screen.getByText(/识别场景与主体/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "开始分析" }));
    expect(state.start).toHaveBeenCalledWith(false);
    expect(state.start).toHaveBeenCalledTimes(1);
  });

  it("shows the real processing stage without a fake percentage", () => {
    renderPanel(
      analysisState({ status: "processing", stage: "vision", running: true }),
    );

    expect(screen.getByText("正在理解照片并识别场景")).toBeInTheDocument();
    const progress = screen.getByRole("progressbar", {
      name: "分析阶段进度",
    });
    expect(progress).toHaveAttribute("aria-valuenow", "1");
    expect(progress).toHaveAttribute("aria-valuemax", "4");
    expect(progress).toHaveAttribute("aria-valuetext", "第 2/4 步 · 识别场景与主体");
    expect(screen.getByText("第 2/4 步 · 识别场景与主体")).toBeInTheDocument();
    expect(
      screen.getByText(/离开页面不会中断分析，返回后会自动接上/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/\d+\s*%/)).not.toBeInTheDocument();
  });

  it("renders the five result sections with severity ordering and mock badge", () => {
    renderPanel(
      analysisState({
        status: "completed",
        stage: "completed",
        isMock: true,
        report: analysisReport(),
      }),
    );

    expect(
      screen.getByText("模拟分析（未调用真实视觉模型）"),
    ).toBeInTheDocument();
    for (const heading of [
      "场景识别",
      "主体识别",
      "光线与色彩",
      "摄影问题",
      "AI 摄影建议",
    ]) {
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    }

    const issues = within(screen.getByRole("region", { name: "摄影问题" }));
    const severityChips = issues.getAllByText(/^严重度/);
    expect(severityChips.map((chip) => chip.textContent)).toEqual([
      "严重度 高",
      "严重度 低",
    ]);

    const recommendations = within(
      screen.getByRole("region", { name: "AI 摄影建议" }),
    );
    const priorities = recommendations.getAllByText(/优先级/);
    expect(priorities.map((chip) => chip.textContent)).toEqual([
      "高优先级",
      "低优先级",
    ]);
    expect(
      recommendations.getByText("对应问题：整体欠曝"),
    ).toBeInTheDocument();

    expect(screen.getByText("协调")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "构图与遮挡" }),
    ).toBeInTheDocument();
    expect(screen.getByText("均衡")).toBeInTheDocument();
    expect(screen.getByText("无遮挡")).toBeInTheDocument();
    expect(screen.getByText("28%")).toBeInTheDocument();
    expect(screen.getByText("1.2°")).toBeInTheDocument();
    expect(
      screen.getByText("提高整体曝光或针对暗部做适度提亮。"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("查看分析依据")).toHaveLength(2);
  });

  it("shows unknown values explicitly and keeps limitations visible", () => {
    const report = analysisReport();
    renderPanel(
      analysisState({
        status: "completed",
        stage: "completed",
        report: {
          ...report,
          subjects: [],
          regions: [],
          lighting: { ...report.lighting, direction: "unknown" },
          color: { ...report.color, temperature: "unknown" },
          composition: {
            ...report.composition,
            occlusion: "unknown",
            subjectAreaRatio: null,
            horizonTiltDeg: null,
          },
          limitations: ["无法可靠检测地平线，未评估画面倾斜。"],
        },
      }),
    );

    expect(screen.getAllByText("未知").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("未评估")).toBeInTheDocument();
    expect(screen.getByText("未检测")).toBeInTheDocument();
    expect(screen.getByText("未识别到明确主体，未生成主体框。")).toBeInTheDocument();
    expect(
      within(screen.getByRole("region", { name: "局限与说明" })).getByText(
        /无法可靠检测地平线，未评估画面倾斜。/,
      ),
    ).toBeInTheDocument();
  });

  it("reuses the original task when retrying a failed analysis", async () => {
    const state = analysisState({
      status: "failed",
      stage: "failed",
      error: {
        code: "provider_unavailable",
        message: "视觉模型暂时不可用。",
        requestId: "req-1",
      },
    });
    renderPanel(state);

    expect(screen.getByText("视觉模型暂时不可用。")).toBeInTheDocument();
    expect(screen.getByText(/provider_unavailable/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(state.retry).toHaveBeenCalledTimes(1);
  });

  it("offers a fresh analysis when a result is already shown", async () => {
    const state = analysisState({
      status: "completed",
      stage: "completed",
      report: analysisReport(),
    });
    renderPanel(state);

    await userEvent.click(screen.getByRole("button", { name: "重新分析" }));
    expect(state.rerun).toHaveBeenCalledTimes(1);
  });

  it("does not render a report that belongs to another image", () => {
    const report = analysisReport({
      image: { ...analysisReport().image, id: ANALYSIS_OTHER_IMAGE_ID },
    });
    renderPanel(
      analysisState({
        status: "completed",
        stage: "completed",
        report,
      }),
    );

    expect(screen.queryByRole("heading", { name: "场景识别" })).not.toBeInTheDocument();
    expect(
      screen.getByText("分析已完成，但结果暂时不可用。"),
    ).toBeInTheDocument();
  });

  it("closes from the header control", async () => {
    const { onClose } = renderPanel(analysisState());
    await userEvent.click(
      screen.getByRole("button", { name: "关闭 AI 摄影分析" }),
    );
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("has no serious or critical axe violations with a completed report", async () => {
    const { container } = renderPanel(
      analysisState({
        status: "completed",
        stage: "completed",
        report: analysisReport(),
      }),
    );

    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    const severe = results.violations.filter(
      (violation) =>
        violation.impact === "serious" || violation.impact === "critical",
    );
    expect(severe).toEqual([]);
  });
});