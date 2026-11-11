import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { HistoryBar } from "@/features/editor/components/history-bar";
import type { RevisionSummary } from "@/types/session";

const ITEMS: RevisionSummary[] = [
  {
    id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    revisionNo: 3,
    parentId: "ffffffff-ffff-4fff-8fff-ffffffffffff",
    source: "ai",
    recipeHash: "hash-3",
    createdAt: "2026-11-02T10:05:00Z",
  },
  {
    id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    revisionNo: 2,
    parentId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    source: "user",
    recipeHash: "hash-2",
    createdAt: "2026-11-02T10:02:00Z",
  },
  {
    id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    revisionNo: 1,
    parentId: null,
    source: "initial",
    recipeHash: "hash-1",
    createdAt: "2026-11-02T10:00:00Z",
  },
];

function renderBar(overrides: Partial<Parameters<typeof HistoryBar>[0]> = {}) {
  const handlers = {
    onUndo: vi.fn(),
    onRedo: vi.fn(),
    onReset: vi.fn(),
    onActivate: vi.fn(),
  };
  render(
    <HistoryBar
      canUndo
      canRedo={false}
      canReset
      items={ITEMS}
      activeRevisionId={ITEMS[1].id}
      {...handlers}
      {...overrides}
    />,
  );
  return handlers;
}

describe("HistoryBar", () => {
  it("disables undo and redo with an explanatory status", async () => {
    const handlers = renderBar({ canUndo: false, canRedo: false });

    expect(screen.getByRole("button", { name: /撤销/ })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(screen.getByRole("button", { name: /重做/ })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(screen.getByRole("status")).toHaveTextContent("没有可撤销或重做的步骤。");

    await userEvent.click(screen.getByRole("button", { name: /撤销/ }));
    expect(handlers.onUndo).not.toHaveBeenCalled();
  });

  it("invokes history actions when enabled", async () => {
    const handlers = renderBar();

    await userEvent.click(screen.getByRole("button", { name: /撤销/ }));
    expect(handlers.onUndo).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: /重置/ }));
    expect(handlers.onReset).toHaveBeenCalledTimes(1);
  });

  it("marks the active revision, sources, and branch points", async () => {
    const { onActivate } = renderBar();

    const active = screen.getByRole("button", { name: /#2 · 手动/ });
    expect(active).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: /#1 · 初始/ })).not.toHaveAttribute(
      "aria-current",
    );
    expect(screen.getByRole("button", { name: /#3 · AI/ })).toBeInTheDocument();
    expect(screen.getByText("分支")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /#3 · AI/ }));
    expect(onActivate).toHaveBeenCalledWith(ITEMS[0].id);
  });

  it("explains when no history exists yet", () => {
    renderBar({ items: [], activeRevisionId: null, canUndo: false, canRedo: false, canReset: false });

    expect(screen.getByText("暂无历史版本。")).toBeInTheDocument();
  });

  it("reports that a version switch is in progress", () => {
    renderBar({ busy: true });

    expect(screen.getByRole("status")).toHaveTextContent("正在切换版本…");
    expect(screen.getByRole("button", { name: /撤销/ })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });

  it("shows generative provenance badge and instruction summary for AI revisions", () => {
    const items: RevisionSummary[] = [
      {
        ...ITEMS[0],
        generative: {
          taskType: "outpaint",
          instructionSummary: "横向延伸海面与晚霞",
          provider: "mock",
          model: "mock-outpaint-v1",
          isMock: true,
          baseMode: "base",
        },
      },
      {
        ...ITEMS[1],
        source: "ai",
        generative: {
          taskType: "local_edit",
          instructionSummary: "增加暖金逆光",
          provider: "qwen",
          model: "qwen-image-edit",
          isMock: false,
          baseMode: "graded",
        },
      },
    ];
    renderBar({ items, activeRevisionId: items[0].id });

    expect(screen.getByText("扩图 · Mock")).toBeInTheDocument();
    expect(screen.getByText(/横向延伸海面与晚霞/)).toBeInTheDocument();
    expect(screen.getByText("局部生成 · qwen")).toBeInTheDocument();
    expect(screen.getByText(/增加暖金逆光/)).toBeInTheDocument();
  });
});
