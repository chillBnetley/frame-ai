import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DeletePhotoDialog } from "@/features/editor/components/delete-photo-dialog";

describe("DeletePhotoDialog", () => {
  it("shows the consequence and focuses the safe action", () => {
    render(
      <DeletePhotoDialog
        open
        busy={false}
        error={null}
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );

    const dialog = screen.getByRole("dialog", { name: "删除这张照片？" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByText(/无法恢复/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "取消" })).toHaveFocus();
  });

  it("cancels on Escape and confirms on the destructive action", async () => {
    const onCancel = vi.fn();
    const onConfirm = vi.fn();
    render(
      <DeletePhotoDialog
        open
        busy={false}
        error={null}
        onCancel={onCancel}
        onConfirm={onConfirm}
      />,
    );

    await userEvent.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: "永久删除" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("blocks both actions and shows the error while deleting", async () => {
    const onCancel = vi.fn();
    render(
      <DeletePhotoDialog
        open
        busy
        error="这张照片正在分析或导出，完成后再删除。"
        onCancel={onCancel}
        onConfirm={vi.fn()}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "这张照片正在分析或导出，完成后再删除。",
    );
    expect(screen.getByRole("button", { name: "正在删除…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "取消" })).toBeDisabled();

    await userEvent.keyboard("{Escape}");
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("renders nothing while closed", () => {
    render(
      <DeletePhotoDialog
        open={false}
        busy={false}
        error={null}
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
