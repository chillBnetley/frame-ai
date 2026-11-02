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
};

function renderDialog(overrides: Partial<Parameters<typeof ExportDialog>[0]> = {}) {
  const onClose = vi.fn();
  const onExport = vi.fn();
  const { unmount } = render(
    <ExportDialog
      open
      onClose={onClose}
      state={IDLE}
      dirty={false}
      onExport={onExport}
      {...overrides}
    />,
  );
  return { onClose, onExport, unmount };
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
    expect(onExport).toHaveBeenCalledWith("png", null);
  });

  it("passes the JPEG quality", async () => {
    const { onExport } = renderDialog();

    fireEvent.change(screen.getByLabelText("JPEG 质量"), { target: { value: "80" } });
    await userEvent.click(screen.getByRole("button", { name: /开始导出/ }));

    expect(onExport).toHaveBeenCalledWith("jpeg", 80);
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
      },
    });
    expect(screen.getByRole("status")).toHaveTextContent(
      "导出完成：frame-abcd1234.jpg（240 × 320，2.0 KB）。",
    );
    expect(screen.getByText("frame-abcd1234.jpg")).toBeInTheDocument();
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
