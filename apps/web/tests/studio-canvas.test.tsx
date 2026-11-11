import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { StudioCanvas } from "@/features/generative/studio/studio-canvas";
import { computeOutpaintGeometry } from "@/lib/generative-canvas";
import type { GenerativeResultView } from "@/types/generative";

const RESULT: GenerativeResultView = {
  resultId: "res-001",
  resultIndex: 0,
  status: "candidate",
  width: 1067,
  height: 600,
  imageUrl: "/api/v1/generative/results/res-001/image",
  warnings: [],
  createdAt: "2026-11-10T12:00:05Z",
};

const OUTPAINT_GEOMETRY = computeOutpaintGeometry({
  baseWidth: 800,
  baseHeight: 600,
  margins: { top: 0, bottom: 0, left: 0, right: 0 },
  aspectRatio: "16:9",
  alignment: "center",
});

function setupCanvas(overrides: Partial<React.ComponentProps<typeof StudioCanvas>> = {}) {
  const props: React.ComponentProps<typeof StudioCanvas> = {
    baseImageUrl: "/preview/current.png",
    originalImageUrl: "/images/original.png",
    result: null,
    baseLayer: "current",
    resultVisible: true,
    maskOverlayVisible: true,
    maskImageUrl: null,
    outpaintGeometry: null,
    baseWidth: 800,
    baseHeight: 600,
    view: { scale: 1, offsetX: 0, offsetY: 0 },
    compare: "off",
    comparePosition: 50,
    isRunning: false,
    stageLabel: null,
    onZoom: vi.fn(),
    onPan: vi.fn(),
    onFit: vi.fn(),
    onComparePositionChange: vi.fn(),
    onViewportSize: vi.fn(),
    ...overrides,
  };

  const { container } = render(<StudioCanvas {...props} />);
  return { props, container, canvas: container.querySelector(".studio-canvas") as HTMLElement };
}

describe("StudioCanvas layers", () => {
  it("shows the rendered preview as the default bottom layer", () => {
    setupCanvas();

    expect(screen.getByRole("img", { name: "当前版本" })).toHaveAttribute(
      "src",
      "/preview/current.png",
    );
    expect(screen.getByText("底图 · 当前版本")).toBeInTheDocument();
  });

  it("switches to the untouched original when the base layer changes", () => {
    setupCanvas({ baseLayer: "original" });

    expect(screen.getByRole("img", { name: "原始照片" })).toHaveAttribute(
      "src",
      "/images/original.png",
    );
    expect(screen.getByText("底图 · 原始照片")).toBeInTheDocument();
  });

  it("waits for a render instead of showing a broken frame", () => {
    setupCanvas({ baseImageUrl: null, originalImageUrl: null });

    expect(screen.getByText("等待渲染预览…")).toBeInTheDocument();
  });

  it("overlays the candidate and hides the mask wash once a result exists", () => {
    setupCanvas({ result: RESULT, maskImageUrl: "/api/v1/generative/masks/m-1/image" });

    expect(screen.getByRole("img", { name: "AI 生成结果" })).toBeInTheDocument();
    expect(screen.getByText("AI 结果")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "" })).not.toBeInTheDocument();
  });

  it("keeps the bottom layer when the candidate preview is turned off", () => {
    setupCanvas({
      result: RESULT,
      resultVisible: false,
      maskImageUrl: "/api/v1/generative/masks/m-1/image",
    });

    expect(screen.queryByRole("img", { name: "AI 生成结果" })).not.toBeInTheDocument();
    expect(screen.getByText("底图 · 当前版本")).toBeInTheDocument();
    expect(screen.getByAltText("")).toHaveAttribute("src", "/api/v1/generative/masks/m-1/image");
  });

  it("hides the mask wash when the overlay is toggled off", () => {
    setupCanvas({ maskOverlayVisible: false, maskImageUrl: "/api/v1/generative/masks/m-1/image" });

    expect(screen.queryByAltText("")).not.toBeInTheDocument();
  });

  it("labels the live stage while a task runs", () => {
    setupCanvas({ isRunning: true, stageLabel: "AI 正在绘制扩充画面..." });

    expect(screen.getByText("AI 正在绘制扩充画面...")).toBeInTheDocument();
  });
});

describe("StudioCanvas outpaint frame", () => {
  it("draws the target frame and offsets the source inside it", () => {
    setupCanvas({ outpaintGeometry: OUTPAINT_GEOMETRY });

    expect(screen.getByText("虚线为扩充目标画幅 1067 × 600")).toBeInTheDocument();

    const source = screen.getByRole("img", { name: "当前版本" });
    expect(Number(source.style.left.replace("%", ""))).toBeCloseTo((133 / 1067) * 100, 4);
    expect(source.style.top).toBe("0%");
    expect(Number(source.style.width.replace("%", ""))).toBeCloseTo((800 / 1067) * 100, 4);
    expect(source.style.height).toBe("100%");
  });

  it("ignores a geometry that did not expand anything", () => {
    setupCanvas({
      outpaintGeometry: computeOutpaintGeometry({
        baseWidth: 800,
        baseHeight: 600,
        margins: { top: 0, bottom: 0, left: 0, right: 0 },
        aspectRatio: "4:3",
        alignment: "center",
      }),
    });

    expect(screen.queryByText(/虚线为扩充目标画幅/)).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: "当前版本" }).style.width).toBe("100%");
  });
});

describe("StudioCanvas compare modes", () => {
  it("clips the candidate for the slider mode", () => {
    setupCanvas({ result: RESULT, compare: "slider", comparePosition: 40 });

    const result = screen.getByRole("img", { name: "AI 生成结果" });
    expect(result.style.clipPath).toBe("inset(0 0 0 40%)");
    expect(screen.getByRole("slider", { name: "对比位置" })).toHaveValue("40");
  });

  it("moves the split when the range input changes", () => {
    const { props } = setupCanvas({ result: RESULT, compare: "slider", comparePosition: 40 });

    fireEvent.change(screen.getByRole("slider", { name: "对比位置" }), {
      target: { value: "70" },
    });

    expect(props.onComparePositionChange).toHaveBeenCalledWith(70);
  });

  it("renders both panes side by side", () => {
    setupCanvas({ result: RESULT, compare: "side" });

    expect(screen.getByText("修改前 · 当前版本")).toBeInTheDocument();
    expect(screen.getByText("AI 结果")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "生成结果并排对比" })).toBeInTheDocument();
  });
});

describe("StudioCanvas view", () => {
  it("zooms on wheel events around the pointer", () => {
    const onZoom = vi.fn();
    const { canvas } = setupCanvas({ onZoom });

    fireEvent.wheel(canvas, { deltaY: -120, clientX: 100, clientY: 60 });

    expect(onZoom).toHaveBeenCalledTimes(1);
    const [factor] = onZoom.mock.calls[0];
    expect(factor).toBeGreaterThan(1);
  });

  it("shrinks when the wheel scrolls down", () => {
    const onZoom = vi.fn();
    const { canvas } = setupCanvas({ onZoom });

    fireEvent.wheel(canvas, { deltaY: 120 });

    const [factor] = onZoom.mock.calls[0];
    expect(factor).toBeLessThan(1);
  });

  it("pans with the pointer drag delta", () => {
    const onPan = vi.fn();
    const { canvas } = setupCanvas({ onPan });

    fireEvent.pointerDown(canvas, { button: 0, pointerId: 1, clientX: 120, clientY: 80 });
    fireEvent.pointerMove(canvas, { pointerId: 1, clientX: 150, clientY: 60 });

    expect(onPan).toHaveBeenCalledWith(30, -20);

    onPan.mockClear();
    fireEvent.pointerUp(canvas, { pointerId: 1 });
    fireEvent.pointerMove(canvas, { pointerId: 1, clientX: 200, clientY: 200 });

    expect(onPan).not.toHaveBeenCalled();
  });

  it("ignores drags that start with another button", () => {
    const { props, canvas } = setupCanvas();

    fireEvent.pointerDown(canvas, { button: 2, pointerId: 1, clientX: 10, clientY: 10 });
    fireEvent.pointerMove(canvas, { pointerId: 1, clientX: 40, clientY: 40 });

    expect(props.onPan).not.toHaveBeenCalled();
  });

  it("pans and zooms from the keyboard", () => {
    const { props, canvas } = setupCanvas();

    fireEvent.keyDown(canvas, { key: "ArrowRight" });
    fireEvent.keyDown(canvas, { key: "ArrowUp" });
    fireEvent.keyDown(canvas, { key: "+" });
    fireEvent.keyDown(canvas, { key: "-" });

    expect(props.onPan).toHaveBeenNthCalledWith(1, -48, 0);
    expect(props.onPan).toHaveBeenNthCalledWith(2, 0, 48);
    expect(props.onZoom).toHaveBeenNthCalledWith(1, 1.25, 0, 0);
    expect(props.onZoom).toHaveBeenNthCalledWith(2, 1 / 1.25, 0, 0);
  });

  it("reaches every canvas control from the keyboard alone", async () => {
    const user = userEvent.setup();
    const onPan = vi.fn();
    const onZoom = vi.fn();
    const { canvas } = setupCanvas({ onPan, onZoom });

    await user.tab();
    expect(canvas).toHaveFocus();

    await user.keyboard("{ArrowDown}");
    await user.keyboard("-");

    expect(onPan).toHaveBeenCalledWith(0, -48);
    expect(onZoom).toHaveBeenCalledWith(1 / 1.25, 0, 0);
  });

  it("fits the frame once the viewport is measured", () => {
    const observe = vi.fn();
    class StubResizeObserver {
      constructor(private callback: ResizeObserverCallback) {}

      observe(target: Element): void {
        this.callback(
          [{ contentRect: { width: 640, height: 360 }, target } as unknown as ResizeObserverEntry],
          this,
        );
        observe();
      }

      unobserve(): void {}

      disconnect(): void {}
    }
    vi.stubGlobal("ResizeObserver", StubResizeObserver);

    const { props } = setupCanvas({
      baseWidth: OUTPAINT_GEOMETRY.targetWidth,
      baseHeight: OUTPAINT_GEOMETRY.targetHeight,
      outpaintGeometry: OUTPAINT_GEOMETRY,
    });

    expect(observe).toHaveBeenCalled();
    expect(props.onViewportSize).toHaveBeenCalledWith(640, 360);
    expect(props.onFit).toHaveBeenCalledWith(640, 360, 1067, 600);

    vi.unstubAllGlobals();
  });

  it("scales the rendered frame with the view", () => {
    const { container } = setupCanvas({ view: { scale: 0.5, offsetX: 12, offsetY: -8 } });

    const frame = container.querySelector(".studio-canvas > div") as HTMLElement;
    expect(frame.style.width).toBe("400px");
    expect(frame.style.height).toBe("300px");
    expect(frame.style.transform).toBe("translate(12px, -8px)");
  });
});
