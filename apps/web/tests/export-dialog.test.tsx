import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ExportDialog } from "@/features/editor/components/export-dialog";
import type { ExportState } from "@/features/editor/hooks/use-export";

const IDLE: ExportState = {
  status: "idle",
  error: null,
  filename: null,
  width: null,
  height: null,
  bytes: null,
  warnings: [],
};

function renderDialog(overrides: Partial<Parameters<typeof ExportDialog>[0]> = {}) {
  const onClose = vi.fn();
  const onExport = vi.fn();
  const onCancel = vi.fn();
  const { unmount } = render(
    <ExportDialog
      open
      onClose={onClose}
      state={IDLE}
      dirty={false}
      onExport={onExport}
      onCancel={onCancel}
      {...overrides}
    />,
  );
  return { onClose, onExport, onCancel, unmount };
}

describe("ExportDialog", () => {
  it("renders an accessible modal and focuses the primary action", () => {
    renderDialog();

    expect(screen.getByRole("dialog", { name: "导出图像" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /开始导出/ })).toHaveFocus();
  });

  it("exports PNG without a quality value", async () => {
    const { onExport } = renderDialog();

    await userEvent.click(screen.getByRole("radio", { name: /PNG/ }));
    expect(screen.queryByLabelText("JPEG 质量")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /开始导出/ }));
    expect(onExport).toHaveBeenCalledWith("png", null, null);
  });

  it("passes the JPEG quality", async () => {
    const { onExport } = renderDialog();

    fireEvent.change(screen.getByLabelText("JPEG 质量"), { target: { value: "80" } });
    await userEvent.click(screen.getByRole("button", { name: /开始导出/ }));

    expect(onExport).toHaveBeenCalledWith("jpeg", 80, null);
  });

  it("sends no max edge for the default original size", async () => {
    const { onExport } = renderDialog();

    expect(screen.getByRole("radio", { name: /原图尺寸/ })).toBeChecked();
    expect(screen.getByText("原图尺寸（不发送 maxEdge）")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /开始导出/ }));
    expect(onExport).toHaveBeenCalledWith("jpeg", 92, null);
  });

  it("sends the selected size preset as max edge", async () => {
    const { onExport } = renderDialog();

    await userEvent.click(screen.getByRole("radio", { name: /长边 2400/ }));
    expect(screen.getByText("长边 2400 像素（maxEdge）")).toBeInTheDocument();
    expect(screen.queryByLabelText("自定义长边（像素）")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /开始导出/ }));
    expect(onExport).toHaveBeenCalledWith("jpeg", 92, 2400);

    await userEvent.click(screen.getByRole("radio", { name: /长边 1080/ }));
    await userEvent.click(screen.getByRole("button", { name: /开始导出/ }));
    expect(onExport).toHaveBeenLastCalledWith("jpeg", 92, 1080);
  });

  it("sends a custom long edge and treats an empty value as original size", async () => {
    const { onExport } = renderDialog();

    await userEvent.click(screen.getByRole("radio", { name: /自定义/ }));
    const input = screen.getByLabelText("自定义长边（像素）");

    fireEvent.change(input, { target: { value: "3200" } });
    await userEvent.click(screen.getByRole("button", { name: /开始导出/ }));
    expect(onExport).toHaveBeenLastCalledWith("jpeg", 92, 3200);

    fireEvent.change(input, { target: { value: "" } });
    expect(screen.getByText(/留空表示原图尺寸/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /开始导出/ }));
    expect(onExport).toHaveBeenLastCalledWith("jpeg", 92, null);
  });

  it("clamps out-of-range custom sizes and explains the clamp", async () => {
    const { onExport } = renderDialog();

    await userEvent.click(screen.getByRole("radio", { name: /自定义/ }));
    const input = screen.getByLabelText("自定义长边（像素）");

    fireEvent.change(input, { target: { value: "20" } });
    expect(screen.getByText(/已限制到 64–8192 之间，实际使用 64 像素/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /开始导出/ }));
    expect(onExport).toHaveBeenLastCalledWith("jpeg", 92, 64);

    fireEvent.change(input, { target: { value: "99999" } });
    await userEvent.click(screen.getByRole("button", { name: /开始导出/ }));
    expect(onExport).toHaveBeenLastCalledWith("jpeg", 92, 8192);
  });

  it("shows the pinned sRGB colour space", () => {
    renderDialog();

    expect(screen.getByText("色彩空间")).toBeInTheDocument();
    expect(screen.getByText("sRGB（固定，嵌入 ICC）")).toBeInTheDocument();
  });

  it("blocks export while the draft has unsaved changes", () => {
    renderDialog({ dirty: true });

    expect(screen.getByText(/请先保存修改/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /开始导出/ })).toBeDisabled();
  });

  it("announces exporting and success details", () => {
    const { unmount } = renderDialog({
      state: {
        status: "exporting",
        error: null,
        filename: null,
        width: null,
        height: null,
        bytes: null,
        warnings: [],
      },
    });
    expect(screen.getByRole("status")).toHaveTextContent("正在导出");
    expect(screen.getByRole("button", { name: /正在导出/ })).toBeDisabled();
    unmount();

    renderDialog({
      state: {
        status: "success",
        error: null,
        filename: "frame-abcd1234.jpg",
        width: 240,
        height: 320,
        bytes: 2048,
        warnings: [],
      },
    });
    expect(screen.getByRole("status")).toHaveTextContent(
      "导出完成：frame-abcd1234.jpg（240 × 320，2.0 KB）。",
    );
    expect(screen.getByText("frame-abcd1234.jpg")).toBeInTheDocument();
  });

  it("shows the simplified denoise warning after export", () => {
    renderDialog({
      state: {
        status: "success",
        error: null,
        filename: "frame-abcd1234.jpg",
        width: 6000,
        height: 4000,
        bytes: 2048,
        warnings: ["denoise_simplified"],
      },
    });

    expect(
      screen.getByText(/降噪已简化（导出尺寸超过 12 MP）/),
    ).toBeInTheDocument();
    expect(screen.getByText(/改用更小的长边/)).toBeInTheDocument();
  });

  it("offers cancellation while a job is running and announces the cancelled state", async () => {
    const running = {
      status: "exporting" as const,
      error: null,
      filename: null,
      width: null,
      height: null,
      bytes: null,
      warnings: [],
    };
    const { onCancel, unmount } = renderDialog({ state: running });

    await userEvent.click(screen.getByRole("button", { name: "取消导出" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    unmount();

    renderDialog({
      state: {
        ...running,
        status: "cancelled",
      },
    });
    expect(screen.getByRole("status")).toHaveTextContent(
      "导出已取消，可以重新开始。",
    );
  });

  it("announces export failures", () => {
    renderDialog({
      state: {
        status: "error",
        error: { code: "server_busy", message: "正在处理另一张高清导出，请稍后几秒再试。", details: {} },
        filename: null,
        width: null,
        height: null,
        bytes: null,
        warnings: [],
      },
    });

    expect(screen.getByRole("status")).toHaveTextContent(
      "导出失败：正在处理另一张高清导出，请稍后几秒再试。",
    );
  });

  it("closes on Escape and on the close button", async () => {
    const { onClose } = renderDialog();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: "关闭导出对话框" }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("renders nothing while closed", () => {
    renderDialog({ open: false });

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
