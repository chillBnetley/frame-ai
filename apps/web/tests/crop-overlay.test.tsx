import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CropOverlay } from "@/features/editor/components/crop-overlay";

function renderOverlay(overrides: Partial<Parameters<typeof CropOverlay>[0]> = {}) {
  const onChange = vi.fn();
  const onApply = vi.fn();
  const onCancel = vi.fn();
  render(
    <CropOverlay
      imageUrl="/api/v1/previews/base"
      canvasWidth={800}
      canvasHeight={600}
      crop={null}
      onChange={onChange}
      onApply={onApply}
      onCancel={onCancel}
      {...overrides}
    />,
  );
  return { onChange, onApply, onCancel };
}

describe("CropOverlay", () => {
  it("starts from the full frame with four numeric inputs", () => {
    renderOverlay();

    expect(screen.getByRole("spinbutton", { name: "左侧位置 x" })).toHaveValue(0);
    expect(screen.getByRole("spinbutton", { name: "顶部位置 y" })).toHaveValue(0);
    expect(screen.getByRole("spinbutton", { name: "宽度 w" })).toHaveValue(1);
    expect(screen.getByRole("spinbutton", { name: "高度 h" })).toHaveValue(1);
    expect(screen.getByAltText("裁切基准画面")).toHaveAttribute(
      "src",
      "/api/v1/previews/base",
    );
    expect(screen.getByText(/800 × 600/)).toBeInTheDocument();
  });

  it("rounds entered values to two decimals and emits valid crops", () => {
    const { onChange } = renderOverlay({ crop: { x: 0, y: 0, w: 0.5, h: 1 } });

    fireEvent.change(screen.getByRole("spinbutton", { name: "左侧位置 x" }), {
      target: { value: "0.333" },
    });

    expect(onChange).toHaveBeenCalledWith({ x: 0.33, y: 0, w: 0.5, h: 1 });
  });

  it("prevalidates x + w and y + h without emitting invalid crops", () => {
    const { onChange } = renderOverlay({ crop: { x: 0, y: 0, w: 0.5, h: 0.5 } });

    fireEvent.change(screen.getByRole("spinbutton", { name: "左侧位置 x" }), {
      target: { value: "0.6" },
    });
    expect(screen.getByRole("alert")).toHaveTextContent(/x \+ 宽/);
    expect(onChange).not.toHaveBeenCalled();

    fireEvent.change(screen.getByRole("spinbutton", { name: "顶部位置 y" }), {
      target: { value: "0.6" },
    });
    expect(screen.getByRole("alert")).toHaveTextContent(/y \+ 高/);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("nudges the box with the keyboard", () => {
    const { onChange } = renderOverlay({ crop: { x: 0.1, y: 0.2, w: 0.5, h: 0.4 } });
    const mover = screen.getByRole("button", { name: "移动裁切框" });

    fireEvent.keyDown(mover, { key: "ArrowRight" });
    expect(onChange).toHaveBeenLastCalledWith({ x: 0.11, y: 0.2, w: 0.5, h: 0.4 });

    fireEvent.keyDown(mover, { key: "ArrowDown", shiftKey: true });
    expect(onChange).toHaveBeenLastCalledWith({ x: 0.1, y: 0.25, w: 0.5, h: 0.4 });
  });

  it("resizes the box with the keyboard", () => {
    const { onChange } = renderOverlay({ crop: { x: 0, y: 0, w: 0.5, h: 0.5 } });
    const resizer = screen.getByRole("button", { name: "调整裁切框大小" });

    fireEvent.keyDown(resizer, { key: "ArrowRight" });
    expect(onChange).toHaveBeenLastCalledWith({ x: 0, y: 0, w: 0.51, h: 0.5 });

    fireEvent.keyDown(resizer, { key: "ArrowDown" });
    expect(onChange).toHaveBeenLastCalledWith({ x: 0, y: 0, w: 0.5, h: 0.51 });
  });

  it("resets to the full frame and applies or cancels", async () => {
    const { onChange, onApply, onCancel } = renderOverlay({
      crop: { x: 0.1, y: 0.1, w: 0.5, h: 0.5 },
    });

    await userEvent.click(screen.getByRole("button", { name: "全图" }));
    expect(onChange).toHaveBeenCalledWith(null);

    await userEvent.click(screen.getByRole("button", { name: "应用裁切" }));
    expect(onApply).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("blocks apply while the prevalidation error is active", () => {
    renderOverlay({ crop: { x: 0, y: 0, w: 0.5, h: 0.5 } });

    fireEvent.change(screen.getByRole("spinbutton", { name: "左侧位置 x" }), {
      target: { value: "0.6" },
    });

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "应用裁切" })).toBeDisabled();
  });
});
