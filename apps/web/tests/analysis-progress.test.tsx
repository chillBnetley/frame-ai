import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AnalysisProgress } from "@/features/analysis/components/analysis-progress";

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-03T00:00:00Z"));
});

afterEach(() => {
  vi.useRealTimers();
});

function advance(milliseconds: number): void {
  act(() => {
    vi.advanceTimersByTime(milliseconds);
  });
}

describe("AnalysisProgress", () => {
  it("stays at step zero while the task is still queued", () => {
    render(<AnalysisProgress status="pending" stage="queued" startedAt={null} />);

    const progress = screen.getByRole("progressbar", {
      name: "分析阶段进度",
    });
    expect(progress).toHaveAttribute("aria-valuenow", "0");
    expect(progress.children).toHaveLength(4);
    expect(screen.getByText("等待分析")).toBeInTheDocument();
    expect(screen.queryByText(/已用/)).not.toBeInTheDocument();
  });

  it("advances with the stage reported by the backend, not a percentage", () => {
    render(
      <AnalysisProgress status="processing" stage="features" startedAt={null} />,
    );

    expect(
      screen.getByRole("progressbar", { name: "分析阶段进度" }),
    ).toHaveAttribute("aria-valuenow", "2");
    expect(
      screen.getByText("第 3/4 步 · 分析光线与色彩"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/\d+\s*%/)).not.toBeInTheDocument();
  });

  it("ticks the elapsed time every second while running", () => {
    render(
      <AnalysisProgress
        status="processing"
        stage="vision"
        startedAt={Date.now() - 5_000}
      />,
    );
    expect(screen.getByText("已用 5 秒")).toBeInTheDocument();

    advance(1_000);
    expect(screen.getByText("已用 6 秒")).toBeInTheDocument();

    advance(56_000);
    expect(screen.getByText("已用 1 分 2 秒")).toBeInTheDocument();
  });

  it("adds a reassurance hint once the run passes thirty and sixty seconds", () => {
    render(
      <AnalysisProgress
        status="processing"
        stage="diagnosis"
        startedAt={Date.now() - 29_000}
      />,
    );
    expect(screen.queryByText(/比平时慢/)).not.toBeInTheDocument();

    advance(1_000);
    expect(screen.getByText(/比平时慢/)).toBeInTheDocument();

    advance(30_000);
    expect(screen.getByText(/仍在等待模型返回/)).toBeInTheDocument();
  });

  it("stops the timer and hides hints once the task completes", () => {
    render(
      <AnalysisProgress
        status="completed"
        stage="completed"
        startedAt={Date.now() - 90_000}
      />,
    );

    expect(
      screen.getByRole("progressbar", { name: "分析阶段进度" }),
    ).toHaveAttribute("aria-valuenow", "4");
    expect(screen.getByText("分析完成")).toBeInTheDocument();
    expect(screen.queryByText(/已用/)).not.toBeInTheDocument();
    expect(screen.queryByText(/仍在等待模型返回/)).not.toBeInTheDocument();
  });
});
