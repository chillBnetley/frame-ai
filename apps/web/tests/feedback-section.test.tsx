import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FeedbackSection } from "@/features/photographer/components/feedback-section";
import { FEEDBACK_DIMENSIONS } from "@/features/photographer/presentation";
import type { FeedbackRubric } from "@/types/photographer";
import {
  feedbackRecord,
  feedbackState,
  feedbackSummary,
} from "./feedback-fixtures";

describe("FeedbackSection", () => {
  it("explains the empty state without claiming any quality result", () => {
    render(<FeedbackSection feedback={feedbackState()} />);

    expect(screen.getByText("反馈与评分")).toBeInTheDocument();
    expect(screen.getByText(/还没有反馈记录/)).toBeInTheDocument();
    expect(screen.getByText(/不保存照片、指令原文或任何文字备注/)).toBeInTheDocument();
    expect(screen.queryByText(/质量提升/)).not.toBeInTheDocument();
    expect(screen.queryByText(/更好/)).not.toBeInTheDocument();
  });

  it("lists recorded decisions with their anchors, paths and scores", () => {
    render(
      <FeedbackSection
        feedback={feedbackState({
          items: [
            feedbackRecord(),
            feedbackRecord({
              id: "second",
              action: "modified",
              source: "chat",
              isMock: false,
              degraded: true,
              changedPaths: [
                "adjustments.contrast",
                "adjustments.saturation",
                "localAdjustments.mask-1.exposureEv",
              ],
              rubric: null,
            }),
          ],
          summary: feedbackSummary({
            total: 2,
            accepted: 1,
            modified: 1,
            mockCount: 1,
            realCount: 1,
            degradedCount: 1,
            ratedCount: 1,
            changeFrequency: [
              { path: "adjustments.contrast", count: 2 },
              { path: "adjustments.saturation", count: 1 },
            ],
          }),
        })}
      />,
    );

    expect(screen.getByText("已接受 · 摄影方案")).toBeInTheDocument();
    expect(screen.getByText("接受后又手动调整 · 对话调整")).toBeInTheDocument();
    expect(screen.getAllByText("模拟方案")).toHaveLength(1);
    expect(screen.getAllByText("真实方案")).toHaveLength(1);
    expect(screen.getAllByText("已降级")).toHaveLength(1);
    expect(screen.getByText(/局部 mask-1 · 曝光/)).toBeInTheDocument();
    expect(screen.getByText("最常改动的参数：对比度 ×2、饱和度 ×1")).toBeInTheDocument();
    expect(
      screen.getByText("接受、拒绝、修改与重置只记录用户行为，不代表方案在客观质量上更优。"),
    ).toBeInTheDocument();
  });

  it("deletes the row the user asked for", async () => {
    const remove = vi.fn(async () => undefined);
    render(<FeedbackSection feedback={feedbackState({ items: [feedbackRecord()], remove })} />);

    await userEvent.click(screen.getByRole("button", { name: "删除这条反馈记录" }));

    expect(remove).toHaveBeenCalledTimes(1);
  });

  it("offers all ten rubric dimensions once and only 1–5 as answers", async () => {
    const submitted: FeedbackRubric[] = [];
    const submitRating = vi.fn(async (rubric: FeedbackRubric) => {
      submitted.push(rubric);
      return true;
    });
    render(
      <FeedbackSection
        feedback={feedbackState({
          rating: {
            action: "accepted",
            source: "plan",
            planId: null,
            revisionId: null,
          },
          submitRating,
        })}
      />,
    );

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getAllByRole("radiogroup")).toHaveLength(10);
    for (const option of FEEDBACK_DIMENSIONS) {
      const group = within(dialog).getByRole("radiogroup", {
        name: `${option.label}评分（1–5）`,
      });
      expect(within(group).getAllByRole("radio")).toHaveLength(5);
    }
    expect(
      within(dialog).getByRole("button", { name: "保存评分（0/10）" }),
    ).toBeDisabled();

    await userEvent.click(within(dialog).getByRole("radio", { name: "曝光 很好" }));
    await userEvent.click(within(dialog).getByRole("radio", { name: "肤色 尚可" }));
    await userEvent.click(
      within(dialog).getByRole("button", { name: "保存评分（2/10）" }),
    );

    expect(submitRating).toHaveBeenCalledTimes(1);
    expect(submitted[0]).toEqual({ exposure: 5, skinTone: 3 });
  });

  it("keeps the dialog open when the score could not be stored", async () => {
    const submitRating = vi.fn(async () => false);
    render(
      <FeedbackSection
        feedback={feedbackState({
          rating: { action: "accepted", source: null, planId: null, revisionId: null },
          submitRating,
        })}
      />,
    );

    const dialog = screen.getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("radio", { name: "色彩 较好" }));
    await userEvent.click(
      within(dialog).getByRole("button", { name: "保存评分（1/10）" }),
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/暂未保存/);
  });

  it("treats skipping and Escape as no score at all", async () => {
    const dismissRating = vi.fn();
    const submitRating = vi.fn(async () => true);
    render(
      <FeedbackSection
        feedback={feedbackState({
          rating: { action: "accepted", source: null, planId: null, revisionId: null },
          dismissRating,
          submitRating,
        })}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "跳过" }));
    expect(dismissRating).toHaveBeenCalledTimes(1);
    expect(submitRating).not.toHaveBeenCalled();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(dismissRating).toHaveBeenCalledTimes(2);
  });

  it("retries queued decisions and refreshes the history on request", async () => {
    const retryUnsent = vi.fn(async () => true);
    const refresh = vi.fn(async () => undefined);
    render(
      <FeedbackSection
        feedback={feedbackState({ unsent: 2, retryUnsent, refresh })}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "2 条待重发 · 重试" }));
    expect(retryUnsent).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: "刷新" }));
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("reports send and history failures without hiding the records", () => {
    render(
      <FeedbackSection
        feedback={feedbackState({
          items: [feedbackRecord()],
          sendError: { code: "storage_error", message: "反馈写入失败", details: {} },
          historyError: { code: "session_not_found", message: "会话不存在", details: {} },
        })}
      />,
    );

    expect(screen.getByText(/反馈未能保存：反馈写入失败/)).toBeInTheDocument();
    expect(screen.getByText(/反馈历史读取失败：会话不存在/)).toBeInTheDocument();
    expect(screen.getByText("已接受 · 摄影方案")).toBeInTheDocument();
  });
});
