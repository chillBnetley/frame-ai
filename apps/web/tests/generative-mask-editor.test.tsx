import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GenerativeMaskEditor } from "@/features/generative/components/generative-mask-editor";
import * as generativeApi from "@/lib/api/generative";
import type { GenerativeMaskView } from "@/types/generative";

vi.mock("@/lib/api/generative", () => ({
  createGenerativeMask: vi.fn(),
  listGenerativeMasks: vi.fn(),
  getGenerativeMask: vi.fn(),
  deleteGenerativeMask: vi.fn(),
  generativeMaskImageUrl: vi.fn((id: string) => `/api/v1/generative/masks/${id}/image`),
}));

const mockCreateGenerativeMask = vi.mocked(generativeApi.createGenerativeMask);
const mockListGenerativeMasks = vi.mocked(generativeApi.listGenerativeMasks);
const mockDeleteGenerativeMask = vi.mocked(generativeApi.deleteGenerativeMask);

const MOCK_MASK_VIEW: GenerativeMaskView = {
  maskId: "mock-mask-001",
  imageId: "img-001",
  baseGeneratedAssetId: null,
  kind: "brush",
  source: "user",
  coordinateSpace: "base-normalized",
  width: 800,
  height: 600,
  imageUrl: "/api/v1/generative/masks/mock-mask-001/image",
  sha256: "0".repeat(64),
  feather: 2,
  inverted: false,
  quality: {
    coverage: 0.125,
    componentCount: 1,
    touchesBorder: false,
    warnings: [],
  },
  definition: {
    strokes: [
      {
        points: [
          { x: 0.5, y: 0.5 },
          { x: 0.55, y: 0.55 },
        ],
        radius: 0.05,
        hardness: 100,
        mode: "add",
      },
    ],
    expand: 0,
  },
  createdAt: "2026-11-10T12:00:00Z",
};

describe("GenerativeMaskEditor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListGenerativeMasks.mockResolvedValue({ items: [] });
    mockDeleteGenerativeMask.mockResolvedValue(undefined);
  });

  it("renders toolbar, tools, and parameter sliders", async () => {
    render(
      <GenerativeMaskEditor
        sessionId="sess-123"
        imageUrl="/api/v1/previews/test.jpg"
      />,
    );

    expect(screen.getByRole("region", { name: "生成式蒙版编辑器" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "画笔工具" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "橡皮擦工具" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "矩形选区" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "椭圆选区" })).toBeInTheDocument();

    expect(screen.getByLabelText("画笔半径")).toBeInTheDocument();
    expect(screen.getByLabelText("硬度")).toBeInTheDocument();
    expect(screen.getByLabelText("羽化")).toBeInTheDocument();
    expect(screen.getByLabelText("扩展")).toBeInTheDocument();
    expect(screen.getByLabelText("反向蒙版")).toBeInTheDocument();

    expect(screen.getByRole("button", { name: "撤销" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "重做" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "清除所有" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "保存蒙版" })).toBeDisabled();
  });

  it("switches tools and updates active state", async () => {
    const user = userEvent.setup();
    render(<GenerativeMaskEditor sessionId="sess-123" />);

    const brushBtn = screen.getByRole("button", { name: "画笔工具" });
    const rectBtn = screen.getByRole("button", { name: "矩形选区" });
    const eraserBtn = screen.getByRole("button", { name: "橡皮擦工具" });

    expect(brushBtn).toHaveAttribute("aria-pressed", "true");
    expect(rectBtn).toHaveAttribute("aria-pressed", "false");

    await user.click(rectBtn);
    expect(rectBtn).toHaveAttribute("aria-pressed", "true");
    expect(brushBtn).toHaveAttribute("aria-pressed", "false");

    // Rect tool hides brush radius slider
    expect(screen.queryByLabelText("画笔半径")).not.toBeInTheDocument();

    await user.click(eraserBtn);
    expect(eraserBtn).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("画笔半径")).toBeInTheDocument();
  });

  it("allows tuning feather, expand, and invert parameters", async () => {
    const user = userEvent.setup();
    render(<GenerativeMaskEditor sessionId="sess-123" />);

    const featherInput = screen.getByLabelText("羽化");
    fireEvent.change(featherInput, { target: { value: "12" } });
    expect(screen.getByText("羽化: 12px")).toBeInTheDocument();

    const expandInput = screen.getByLabelText("扩展");
    fireEvent.change(expandInput, { target: { value: "5" } });
    expect(screen.getByText("扩展: 5px")).toBeInTheDocument();

    const invertCheck = screen.getByLabelText("反向蒙版");
    expect(invertCheck).not.toBeChecked();
    await user.click(invertCheck);
    expect(invertCheck).toBeChecked();
  });

  it("draws strokes on canvas, enables history actions and clears content", async () => {
    const user = userEvent.setup();
    render(<GenerativeMaskEditor sessionId="sess-123" />);

    const canvas = screen.getByLabelText("蒙版绘制画布");
    const undoBtn = screen.getByRole("button", { name: "撤销" });
    const redoBtn = screen.getByRole("button", { name: "重做" });
    const clearBtn = screen.getByRole("button", { name: "清除所有" });
    const saveBtn = screen.getByRole("button", { name: "保存蒙版" });

    expect(undoBtn).toBeDisabled();
    expect(saveBtn).toBeDisabled();

    // Simulate drawing stroke
    fireEvent.pointerDown(canvas, { clientX: 100, clientY: 100 });
    fireEvent.pointerMove(canvas, { clientX: 150, clientY: 150 });
    fireEvent.pointerUp(canvas);

    expect(undoBtn).toBeEnabled();
    expect(clearBtn).toBeEnabled();
    expect(saveBtn).toBeEnabled();

    // Undo reverts stroke
    await user.click(undoBtn);
    expect(undoBtn).toBeDisabled();
    expect(redoBtn).toBeEnabled();
    expect(saveBtn).toBeDisabled();

    // Redo restores stroke
    await user.click(redoBtn);
    expect(undoBtn).toBeEnabled();
    expect(saveBtn).toBeEnabled();

    // Clear removes all content
    await user.click(clearBtn);
    expect(saveBtn).toBeDisabled();
  });

  it("submits manual mask and triggers onMaskCreated with quality report", async () => {
    const user = userEvent.setup();
    const handleCreated = vi.fn();
    mockCreateGenerativeMask.mockResolvedValue(MOCK_MASK_VIEW);

    render(
      <GenerativeMaskEditor
        sessionId="sess-123"
        onMaskCreated={handleCreated}
      />,
    );

    const canvas = screen.getByLabelText("蒙版绘制画布");
    fireEvent.pointerDown(canvas, { clientX: 200, clientY: 200 });
    fireEvent.pointerMove(canvas, { clientX: 250, clientY: 250 });
    fireEvent.pointerUp(canvas);

    const saveBtn = screen.getByRole("button", { name: "保存蒙版" });
    await user.click(saveBtn);

    await waitFor(() => {
      expect(mockCreateGenerativeMask).toHaveBeenCalledWith(
        expect.objectContaining({
          sessionId: "sess-123",
          kind: "brush",
          definition: expect.objectContaining({
            strokes: expect.any(Array),
            region: null,
          }),
        }),
      );
    });

    expect(handleCreated).toHaveBeenCalledWith(MOCK_MASK_VIEW);

    // Quality report is displayed
    expect(screen.getByRole("status", { name: "蒙版质量报告" })).toBeInTheDocument();
    expect(screen.getByText("覆盖率: 12.50%")).toBeInTheDocument();
    expect(screen.getByText("连通区: 1")).toBeInTheDocument();
  });

  it("creates semantic person mask directly via AI assist button", async () => {
    const user = userEvent.setup();
    const handleCreated = vi.fn();
    mockCreateGenerativeMask.mockResolvedValue({
      ...MOCK_MASK_VIEW,
      kind: "semantic",
      source: "semantic",
      definition: { semanticClass: "person", expand: 0 },
    });

    render(
      <GenerativeMaskEditor
        sessionId="sess-123"
        onMaskCreated={handleCreated}
      />,
    );

    const personBtn = screen.getByRole("button", { name: "生成人物蒙版" });
    await user.click(personBtn);

    await waitFor(() => {
      expect(mockCreateGenerativeMask).toHaveBeenCalledWith(
        expect.objectContaining({
          sessionId: "sess-123",
          kind: "semantic",
          definition: expect.objectContaining({
            semanticClass: "person",
          }),
        }),
      );
    });

    expect(handleCreated).toHaveBeenCalled();
  });

  it("lists previously saved masks and allows deleting one", async () => {
    const user = userEvent.setup();
    mockListGenerativeMasks.mockResolvedValue({
      items: [
        {
          ...MOCK_MASK_VIEW,
          maskId: "saved-mask-999",
          kind: "rect",
        },
      ],
    });

    render(<GenerativeMaskEditor sessionId="sess-123" />);

    await waitFor(() => {
      expect(screen.getByText("已存蒙版 (1)")).toBeInTheDocument();
      expect(screen.getByText("rect")).toBeInTheDocument();
    });

    const deleteBtn = screen.getByRole("button", { name: "删除蒙版 saved-mask-999" });
    await user.click(deleteBtn);

    await waitFor(() => {
      expect(mockDeleteGenerativeMask).toHaveBeenCalledWith("saved-mask-999");
    });
  });

  it("displays server error message on submit failure", async () => {
    const user = userEvent.setup();
    mockCreateGenerativeMask.mockRejectedValue({
      details: {
        reasons: ["所选区域覆盖率太小", "笔触超出边界"],
      },
    });

    render(<GenerativeMaskEditor sessionId="sess-123" />);

    const canvas = screen.getByLabelText("蒙版绘制画布");
    fireEvent.pointerDown(canvas, { clientX: 200, clientY: 200 });
    fireEvent.pointerUp(canvas);

    const saveBtn = screen.getByRole("button", { name: "保存蒙版" });
    await user.click(saveBtn);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("所选区域覆盖率太小；笔触超出边界");
    });
  });

  it("has no serious or critical accessibility violations", async () => {
    const { container } = render(
      <GenerativeMaskEditor
        sessionId="sess-123"
        imageUrl="/api/v1/previews/test.jpg"
      />,
    );
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    const severe = results.violations.filter(
      (v) => v.impact === "serious" || v.impact === "critical",
    );
    expect(severe).toEqual([]);
  });
});
