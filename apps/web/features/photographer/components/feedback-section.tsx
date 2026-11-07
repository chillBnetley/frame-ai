"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import type { UseFeedbackResult } from "@/features/photographer/hooks/use-feedback";
import {
  changeLabel,
  FEEDBACK_ACTION_LABELS,
  FEEDBACK_DIMENSIONS,
  FEEDBACK_NOT_QUALITY_NOTE,
  FEEDBACK_PRIVACY_NOTE,
  FEEDBACK_SOURCE_LABELS,
  SCORE_LABELS,
} from "@/features/photographer/presentation";
import type {
  FeedbackDimension,
  FeedbackRubric,
  PhotographerFeedback,
} from "@/types/photographer";

const sectionTitle = "text-[11px] font-medium text-white/70";
const chip =
  "inline-flex min-h-6 items-center rounded-md border px-2 text-[10px]";
const neutralChip = `${chip} border-white/12 bg-white/[0.03] text-white/55`;
const warnChip = `${chip} border-amber-300/25 bg-amber-300/10 text-amber-100`;
const dangerButton =
  "inline-flex min-h-8 items-center rounded-md border border-white/12 px-2 text-[10px] text-white/50 transition-colors hover:border-red-300/40 hover:text-red-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-40";
const dialogButton =
  "inline-flex min-h-11 items-center justify-center rounded-lg px-4 text-xs transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-40";

const SCORES = [1, 2, 3, 4, 5] as const;

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("zh-CN", { hour12: false });
}

function rubricEntries(
  rubric: FeedbackRubric | null | undefined,
): { key: FeedbackDimension; score: number }[] {
  if (!rubric) {
    return [];
  }
  return FEEDBACK_DIMENSIONS.map((option) => ({
    key: option.key,
    score: Number(rubric[option.key] ?? Number.NaN),
  })).filter((entry) => Number.isFinite(entry.score));
}

interface RatingDialogProps {
  onClose: () => void;
  onSubmit: (rubric: FeedbackRubric) => Promise<boolean>;
}

/** The optional 1–5 rubric. Every dimension may be left unscored. */
function RatingDialog({ onClose, onSubmit }: RatingDialogProps) {
  const [scores, setScores] = useState<Partial<Record<FeedbackDimension, number>>>(
    {},
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  // The dialog opens on top of the accept button; hand focus over and back.
  useEffect(() => {
    const previous =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    dialogRef.current?.focus();
    return () => previous?.focus();
  }, []);

  // Escape is "skip": the decision is already recorded without a score.
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const scoredCount = FEEDBACK_DIMENSIONS.filter(
    (option) => scores[option.key] !== undefined,
  ).length;

  const submit = useCallback(async () => {
    const rubric: FeedbackRubric = {};
    for (const option of FEEDBACK_DIMENSIONS) {
      const value = scores[option.key];
      if (value !== undefined) {
        rubric[option.key] = value;
      }
    }
    setSubmitting(true);
    setError(null);
    const stored = await onSubmit(rubric);
    setSubmitting(false);
    if (stored) {
      onClose();
      return;
    }
    setError("评分暂未保存，可在反馈记录里重试。");
  }, [onClose, onSubmit, scores]);

  // Portalled: the panel that opens this dialog lives inside a backdrop-blur
  // card, and a filtered ancestor becomes the containing block of `fixed`.
  return createPortal(
    <div className="fixed inset-0 z-50 grid place-items-center bg-[rgba(241,243,242,0.72)] p-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        aria-labelledby="feedback-rating-title"
        className="w-full max-w-lg rounded-2xl border border-white/12 bg-[#101113] p-5 shadow-[0_30px_80px_-20px_rgba(0,0,0,0.9)]"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 id="feedback-rating-title" className="text-sm font-medium text-white">
              这次结果的主观评分（可跳过）
            </h2>
            <p className="mt-1 text-[11px] text-white/40">{FEEDBACK_NOT_QUALITY_NOTE}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭评分对话框"
            className="grid size-11 place-items-center rounded-lg text-white/45 transition-colors hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            <span aria-hidden="true">✕</span>
          </button>
        </div>

        <div className="mt-4 grid max-h-[52vh] gap-2 overflow-y-auto pr-1">
          {FEEDBACK_DIMENSIONS.map((option) => (
            <div
              key={option.key}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/8 bg-white/[0.02] px-3 py-2"
            >
              <span className="text-[11px] text-white/75">{option.label}</span>
              <div
                role="radiogroup"
                aria-label={`${option.label}评分（1–5）`}
                className="flex items-center gap-1"
              >
                {SCORES.map((score) => (
                  <button
                    key={score}
                    type="button"
                    role="radio"
                    aria-checked={scores[option.key] === score}
                    title={SCORE_LABELS[score]}
                    aria-label={`${option.label} ${SCORE_LABELS[score]}`}
                    onClick={() =>
                      setScores((current) => ({
                        ...current,
                        [option.key]: current[option.key] === score ? undefined : score,
                      }))
                    }
                    className={`grid size-8 place-items-center rounded-md border text-[11px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
                      scores[option.key] === score
                        ? "border-accent/45 bg-accent/15 text-accent"
                        : "border-white/12 bg-white/[0.03] text-white/55 hover:bg-white/[0.08]"
                    }`}
                  >
                    {score}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>

        <p className="mt-3 text-[10px] text-white/35">{FEEDBACK_PRIVACY_NOTE}</p>

        {error !== null && (
          <p role="alert" className="mt-2 text-[11px] text-red-200/90">
            评分保存失败：{error}
          </p>
        )}

        <div className="mt-4 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className={`${dialogButton} border border-white/12 text-white/60 hover:bg-white/[0.05] hover:text-white`}
          >
            跳过
          </button>
          <button
            type="button"
            disabled={submitting || scoredCount === 0}
            onClick={() => void submit()}
            className={`${dialogButton} bg-accent font-semibold text-[#101208] hover:bg-accent/85`}
          >
            {submitting ? "正在保存…" : `保存评分（${scoredCount}/10）`}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

function dimensionLabel(key: FeedbackDimension): string {
  return FEEDBACK_DIMENSIONS.find((option) => option.key === key)?.label ?? key;
}

function FeedbackItemRow({
  item,
  onDelete,
}: {
  item: PhotographerFeedback;
  onDelete: (id: string) => Promise<void>;
}) {
  const [deleting, setDeleting] = useState(false);
  const paths = item.changedPaths.slice(0, 4);
  const rated = rubricEntries(item.rubric);

  return (
    <li className="grid gap-1.5 rounded-lg border border-white/8 bg-white/[0.02] px-3 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-[11px] text-white/75">
          {item.source
            ? `${FEEDBACK_ACTION_LABELS[item.action]} · ${FEEDBACK_SOURCE_LABELS[item.source]}`
            : FEEDBACK_ACTION_LABELS[item.action]}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="font-mono text-[10px] text-white/35">
            {formatTime(item.createdAt)}
          </span>
          <button
            type="button"
            disabled={deleting}
            aria-label="删除这条反馈记录"
            onClick={async () => {
              setDeleting(true);
              try {
                await onDelete(item.id);
              } finally {
                setDeleting(false);
              }
            }}
            className={dangerButton}
          >
            {deleting ? "删除中…" : "删除"}
          </button>
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        {item.isMock ? (
          <span className={warnChip}>模拟方案</span>
        ) : (
          <span className={neutralChip}>真实方案</span>
        )}
        {item.degraded && <span className={warnChip}>已降级</span>}
      </div>

      {paths.length > 0 && (
        <p className="text-[10px] text-white/40">
          改动：{paths.map(changeLabel).join("、")}
          {item.changedPaths.length > paths.length
            ? ` 等 ${item.changedPaths.length} 项`
            : ""}
        </p>
      )}

      {rated.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {rated.map((entry) => (
            <span key={entry.key} className={neutralChip}>
              {dimensionLabel(entry.key)} {entry.score}
            </span>
          ))}
        </div>
      )}
    </li>
  );
}

interface FeedbackSectionProps {
  feedback: UseFeedbackResult;
}

/** Records what the user did; never presents those records as measured quality. */
export function FeedbackSection({ feedback }: FeedbackSectionProps) {
  const summary = feedback.summary;
  const frequency = useMemo(
    () => summary?.changeFrequency.slice(0, 3) ?? [],
    [summary?.changeFrequency],
  );

  return (
    <section aria-label="反馈与评分" className="grid gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className={sectionTitle}>反馈与评分</h4>
        <div className="flex items-center gap-1.5">
          {feedback.unsent > 0 && (
            <button
              type="button"
              onClick={() => void feedback.retryUnsent()}
              className={warnChip}
            >
              {feedback.unsent} 条待重发 · 重试
            </button>
          )}
          <button
            type="button"
            onClick={() => void feedback.refresh()}
            disabled={feedback.loading}
            className={dangerButton}
          >
            {feedback.loading ? "读取中…" : "刷新"}
          </button>
        </div>
      </div>

      {feedback.rating !== null && (
        <RatingDialog
          onClose={feedback.dismissRating}
          onSubmit={feedback.submitRating}
        />
      )}

      {feedback.sendError !== null && (
        <p role="alert" className="text-[10px] text-amber-100">
          反馈未能保存：{feedback.sendError.message}
        </p>
      )}
      {feedback.historyError !== null && (
        <p role="alert" className="text-[10px] text-red-200/90">
          反馈历史读取失败：{feedback.historyError.message}
        </p>
      )}

      {summary !== null && summary.total > 0 && (
        <div className="grid gap-1.5">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className={neutralChip}>接受 {summary.accepted}</span>
            <span className={neutralChip}>接受后调整 {summary.modified}</span>
            <span className={neutralChip}>拒绝 {summary.rejected}</span>
            <span className={neutralChip}>重置 {summary.reset}</span>
            <span className={neutralChip}>已评分 {summary.ratedCount}</span>
            <span className={neutralChip}>模拟 {summary.mockCount}</span>
            <span className={neutralChip}>真实 {summary.realCount}</span>
            {summary.degradedCount > 0 && (
              <span className={warnChip}>降级 {summary.degradedCount}</span>
            )}
          </div>
          {frequency.length > 0 && (
            <p className="text-[10px] text-white/40">
              最常改动的参数：
              {frequency
                .map((entry) => `${changeLabel(entry.path)} ×${entry.count}`)
                .join("、")}
            </p>
          )}
          {summary.disclaimers.length > 0 && (
            <p className="text-[10px] text-white/35">{summary.disclaimers[0]}</p>
          )}
        </div>
      )}

      {feedback.items.length === 0 ? (
        <p className="text-[11px] text-white/35">
          还没有反馈记录。接受或放弃方案时会自动记录，你可以随时删除。
        </p>
      ) : (
        <ul className="grid gap-1.5">
          {feedback.items.map((item) => (
            <FeedbackItemRow
              key={item.id}
              item={item}
              onDelete={feedback.remove}
            />
          ))}
        </ul>
      )}

      <p className="text-[10px] text-white/35">{FEEDBACK_PRIVACY_NOTE}</p>
    </section>
  );
}
