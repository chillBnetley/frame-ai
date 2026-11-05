import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AdjustmentPanel } from "@/features/editor/components/adjustment-panel";
import { DEFAULT_ADJUSTMENTS } from "@/lib/recipe";
import type { Adjustments } from "@/types/session";

function renderPanel(overrides: Partial<Parameters<typeof AdjustmentPanel>[0]> = {}) {
  const onChange = vi.fn();
  const onCommit = vi.fn();
  const onOpenCrop = vi.fn();
  const onClearCrop = vi.fn();
  render(
    <AdjustmentPanel
      adjustments={DEFAULT_ADJUSTMENTS}
      onChange={onChange}
      onCommit={onCommit}
      onOpenCrop={onOpenCrop}
      onClearCrop={onClearCrop}
      {...overrides}
    />,
  );
  return { onChange, onCommit, onOpenCrop, onClearCrop };
}

describe("AdjustmentPanel", () => {
  it("renders all five groups with their controls", () => {
    renderPanel();

    for (const title of ["光线", "色彩", "细节", "效果", "几何"]) {
      expect(screen.getByText(title)).toBeInTheDocument();
    }
    for (const label of [
      "曝光",
      "对比度",
      "高光",
      "阴影",
      "白色色阶",
      "黑色色阶",
      "色温",
      "色调",
      "饱和度",
      "自然饱和度",
      "降噪",
      "颗粒",
      "旋转",
    ]) {
      expect(screen.getByRole("slider", { name: label })).toBeInTheDocument();
    }

    expect(screen.getByRole("slider", { name: "曝光" })).toHaveAttribute("step", "0.01");
    expect(screen.getByRole("slider", { name: "对比度" })).toHaveAttribute("step", "1");
    expect(screen.getByRole("slider", { name: "白色色阶" })).toHaveAttribute("step", "1");
  });

  it("warns that rotation crops the edges", () => {
    renderPanel();

    expect(screen.getByText(/旋转会裁掉边缘/)).toBeInTheDocument();
  });

  it("reports adjustment changes and commits", () => {
    const { onChange, onCommit } = renderPanel();
    const slider = screen.getByRole("slider", { name: "曝光" });

    fireEvent.change(slider, { target: { value: "1.5" } });
    expect(onChange).toHaveBeenCalledWith("exposureEv", 1.5);

    fireEvent.pointerUp(slider);
    expect(onCommit).toHaveBeenCalled();
  });

  it("reports whites and blacks changes with their own keys", () => {
    const { onChange } = renderPanel();

    fireEvent.change(screen.getByRole("slider", { name: "白色色阶" }), {
      target: { value: "40" },
    });
    expect(onChange).toHaveBeenCalledWith("whites", 40);

    fireEvent.change(screen.getByRole("slider", { name: "黑色色阶" }), {
      target: { value: "-35" },
    });
    expect(onChange).toHaveBeenCalledWith("blacks", -35);
  });

  it("shows the crop summary and opens the crop editor", async () => {
    const crop = { x: 0.1, y: 0.2, w: 0.5, h: 0.4 };
    const adjustments: Adjustments = { ...DEFAULT_ADJUSTMENTS, crop };
    const { onOpenCrop, onClearCrop } = renderPanel({ adjustments });

    expect(screen.getByText(/x 10% · y 20% · 宽 50% · 高 40%/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "清除裁切" })).toBeEnabled();

    await userEvent.click(screen.getByRole("button", { name: "调整裁切" }));
    expect(onOpenCrop).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: "清除裁切" }));
    expect(onClearCrop).toHaveBeenCalledTimes(1);
  });

  it("disables clear-crop when the full frame is used", () => {
    renderPanel();

    expect(screen.getByText("全图（未裁切）")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "清除裁切" })).toBeDisabled();
  });

  it("disables every control while busy", () => {
    renderPanel({ disabled: true });

    expect(screen.getByRole("slider", { name: "曝光" })).toBeDisabled();
    expect(screen.getByRole("slider", { name: "白色色阶" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "调整裁切" })).toBeDisabled();
  });
});
