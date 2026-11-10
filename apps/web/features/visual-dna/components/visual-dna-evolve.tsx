"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { MasterVisionStatus } from "@/features/master-vision/components/status";
import { ApiClientError } from "@/lib/api/client";
import { fetchPersonalStyle } from "@/lib/api/personal-style";
import {
  addStyleFeedback,
  applyStyleEvolution,
  deleteStyleFeedback,
  discardStyleEvolution,
  listStyleEvolutions,
  listStyleFeedback,
  previewStyleEvolution,
} from "@/lib/api/style-evolution";
import type { PersonalStyleDetailResponse } from "@/types/personal-style";
import type {
  StyleEvolutionPreviewResponse,
  StyleEvolutionRecord,
  StyleFeedbackRecord,
  StyleFeedbackScope,
  StyleFeedbackType,
} from "@/types/style-evolution";

import { VisualDnaNav } from "./visual-dna-nav";
import {
  EVOLUTION_STATUS_LABELS,
  FEEDBACK_SCOPE_HINTS,
  FEEDBACK_SCOPE_LABELS,
  FEEDBACK_TYPES,
  FEEDBACK_TYPE_LABELS,
  formatChangeValue,
  formatDateTime,
  formatTargetValue,
} from "../presentation";

type Busy = "feedback" | "delete" | "preview" | "apply" | "discard" | null;

const SCOPE_ORDER: StyleFeedbackScope[] = ["single_edit", "profile"];

function actionError(reason: unknown, fallback: string): string {
  return reason instanceof ApiClientError ? reason.message : fallback;
}

function formatAdjustment(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return formatTargetValue(value);
  if (Array.isArray(value)) {
    return value.length === 0 ? "无" : value.map((item) => String(item)).join("、");
  }
  if (typeof value === "boolean") return value ? "是" : "否";
  return String(value);
}

export function VisualDnaEvolve({ styleId }: { styleId: string }) {
  const router = useRouter();
  const [detail, setDetail] = useState<PersonalStyleDetailResponse | null>(null);
  const [feedbacks, setFeedbacks] = useState<StyleFeedbackRecord[]>([]);
  const [evolutions, setEvolutions] = useState<StyleEvolutionRecord[]>([]);
  const [feedbackType, setFeedbackType] = useState<StyleFeedbackType>("like_result");
  const [scope, setScope] = useState<StyleFeedbackScope>("single_edit");
  const [note, setNote] = useState("");
  const [preview, setPreview] = useState<StyleEvolutionPreviewResponse | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      fetchPersonalStyle(styleId, { signal: controller.signal }),
      listStyleFeedback(styleId, { signal: controller.signal }),
      listStyleEvolutions(styleId, controller.signal),
    ])
      .then(([nextDetail, nextFeedback, nextEvolutions]) => {
        if (controller.signal.aborted) return;
        setDetail(nextDetail);
        setFeedbacks(nextFeedback.feedbacks);
        setEvolutions(nextEvolutions.evolutions);
        setLoadError(null);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setLoadError(
            actionError(reason, "无法加载反馈与版本记录，请确认 API 服务已经启动。"),
          );
        }
      });
    return () => controller.abort();
  }, [attempt, styleId]);

  const refreshFeedback = useCallback(async () => {
    const next = await listStyleFeedback(styleId);
    setFeedbacks(next.feedbacks);
  }, [styleId]);

  const refreshEvolutions = useCallback(async () => {
    const next = await listStyleEvolutions(styleId);
    setEvolutions(next.evolutions);
  }, [styleId]);

  async function handleRecordFeedback() {
    setBusy("feedback");
    setError(null);
    setMessage(null);
    setPreview(null);
    try {
      await addStyleFeedback(styleId, {
        feedbackType,
        scope,
        note: note.trim().length > 0 ? note.trim() : undefined,
      });
      await refreshFeedback();
      setNote("");
      setMessage(
        scope === "profile"
          ? "已作为个人风格反馈记录，生成候选前不会修改风格。"
          : "已记录本次调整反馈，不会影响个人风格。",
      );
    } catch (reason: unknown) {
      setError(actionError(reason, "记录反馈失败，请稍后重试。"));
    } finally {
      setBusy(null);
    }
  }

  async function handleDeleteFeedback(feedback: StyleFeedbackRecord) {
    setBusy("delete");
    setError(null);
    setMessage(null);
    try {
      await deleteStyleFeedback(styleId, feedback.id);
      await refreshFeedback();
    } catch (reason: unknown) {
      setError(actionError(reason, "删除反馈失败。"));
    } finally {
      setBusy(null);
    }
  }

  async function handlePreview() {
    setBusy("preview");
    setError(null);
    setMessage(null);
    try {
      const next = await previewStyleEvolution(styleId, {});
      setPreview(next);
      await refreshEvolutions();
    } catch (reason: unknown) {
      setError(
        actionError(
          reason,
          "无法生成演变候选。请先记录至少一条「加入个人风格」的反馈。",
        ),
      );
    } finally {
      setBusy(null);
    }
  }

  async function handleApply() {
    if (preview === null) return;
    setBusy("apply");
    setError(null);
    setMessage(null);
    try {
      await applyStyleEvolution(styleId, preview.evolution.id, {
        note: preview.evolution.reason,
      });
      router.push(`/visual-dna/${encodeURIComponent(styleId)}`);
    } catch (reason: unknown) {
      setError(actionError(reason, "应用演变失败，请稍后重试。"));
      setBusy(null);
    }
  }

  async function handleDiscard() {
    if (preview === null) return;
    setBusy("discard");
    setError(null);
    setMessage(null);
    try {
      await discardStyleEvolution(styleId, preview.evolution.id);
      setPreview(null);
      await refreshEvolutions();
      setMessage("已放弃该候选，个人风格保持不变。");
    } catch (reason: unknown) {
      setError(actionError(reason, "放弃候选失败。"));
    } finally {
      setBusy(null);
    }
  }

  if (loadError !== null) {
    return (
      <main className="mx-auto w-full max-w-[1080px] px-4 py-6 sm:px-6 lg:px-8">
        <VisualDnaNav />
        <div className="mt-5">
          <MasterVisionStatus
            tone="error"
            title="反馈演变加载失败"
            action={
              <button
                type="button"
                onClick={() => setAttempt((value) => value + 1)}
                className="min-h-9 rounded-lg border border-[#e6bdb7] bg-white px-3 text-xs font-medium text-[#8a3a2e] hover:bg-[#fff7f5] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                重新加载
              </button>
            }
          >
            {loadError}
          </MasterVisionStatus>
        </div>
      </main>
    );
  }

  if (detail === null) {
    return (
      <main className="mx-auto w-full max-w-[1080px] px-4 py-6 sm:px-6 lg:px-8">
        <VisualDnaNav />
        <div className="mt-6 h-40 animate-pulse rounded-2xl border border-[#e4e8e5] bg-[#f4f7f5]" />
      </main>
    );
  }

  const pendingProfile = feedbacks.filter(
    (item) => item.scope === "profile" && (item.appliedVersion ?? null) === null,
  ).length;
  const disabled = busy !== null;

  return (
    <main className="mx-auto w-full max-w-[1080px] px-4 py-6 sm:px-6 lg:px-8">
      <VisualDnaNav />
      <div className="mt-6 flex flex-wrap items-end justify-between gap-4 border-b border-[#e4e8e5] pb-5">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.28em] text-[#8a9a93]">
            STYLE EVOLUTION
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-[-0.045em] text-[#1d2521]">
            「{detail.style.name}」反馈演变
          </h1>
          <p className="mt-2 text-sm text-[#68746e]">
            当前 v{detail.style.version}。单次反馈不会改变风格，只有你确认「加入个人风格」并最终确认候选后才会生成新版本。
          </p>
        </div>
        <Link
          href={`/visual-dna/${encodeURIComponent(styleId)}`}
          className="text-xs font-medium text-[#277a68] hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          ← 返回工作台
        </Link>
      </div>

      <section className="mt-6 rounded-2xl border border-[#dfe5e1] bg-white p-5">
        <h2 className="text-sm font-semibold text-[#202522]">记录反馈</h2>
        <div className="mt-3 flex flex-wrap gap-2">
          {FEEDBACK_TYPES.map((type) => (
            <button
              key={type}
              type="button"
              aria-pressed={feedbackType === type}
              onClick={() => setFeedbackType(type)}
              className="inline-flex min-h-8 items-center rounded-full border border-[#dfe5e1] bg-white px-2.5 text-[10px] text-[#5f6d66] hover:border-[#b9cdc2] hover:bg-[#f7faf8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent aria-pressed:border-[#bfd5ca] aria-pressed:bg-[#f0f7f4] aria-pressed:text-[#277a68]"
            >
              {FEEDBACK_TYPE_LABELS[type]}
            </button>
          ))}
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          {SCOPE_ORDER.map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={scope === option}
              onClick={() => setScope(option)}
              className="inline-flex min-h-9 items-center rounded-xl border border-[#d7dfda] bg-white px-3 text-xs font-medium text-[#415049] hover:bg-[#f7faf8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent aria-pressed:border-[#9dbdaf] aria-pressed:bg-[#f0f7f4] aria-pressed:text-[#277a68]"
            >
              {FEEDBACK_SCOPE_LABELS[option]}
            </button>
          ))}
        </div>
        <p className="mt-2 text-[11px] text-[#8a9690]">{FEEDBACK_SCOPE_HINTS[scope]}</p>

        <textarea
          value={note}
          onChange={(event) => setNote(event.target.value)}
          maxLength={500}
          rows={3}
          placeholder="可选：用一句话补充你的具体意见，例如「肤色有点偏冷」。"
          className="mt-3 w-full rounded-xl border border-[#dfe5e1] px-3.5 py-3 text-sm leading-relaxed text-[#2a3530] placeholder:text-[#a4aea9] focus:border-[#9dbdaf] focus:outline-none"
        />
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <p className="text-[11px] text-[#8a9690]">
            已记录个人风格反馈 {pendingProfile} 条待演变。
          </p>
          <button
            type="button"
            disabled={disabled}
            onClick={() => void handleRecordFeedback()}
            className="inline-flex min-h-10 items-center rounded-xl bg-[#277a68] px-4 text-xs font-medium text-white hover:bg-[#206557] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy === "feedback" ? "正在记录…" : "记录反馈"}
          </button>
        </div>
      </section>

      {error !== null && (
        <div className="mt-4">
          <MasterVisionStatus tone="error" title="操作未完成">
            {error}
          </MasterVisionStatus>
        </div>
      )}
      {message !== null && (
        <div className="mt-4">
          <MasterVisionStatus tone="success" title="操作完成">
            {message}
          </MasterVisionStatus>
        </div>
      )}

      <section className="mt-6 rounded-2xl border border-[#dfe5e1] bg-white p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-[#202522]">演变候选</h2>
            <p className="mt-1 text-[11px] text-[#8a9690]">
              按「加入个人风格」且尚未应用的反馈生成有界候选，确认前不会修改风格。
            </p>
          </div>
          <button
            type="button"
            disabled={disabled || pendingProfile === 0}
            onClick={() => void handlePreview()}
            className="inline-flex min-h-10 items-center rounded-xl border border-[#d7dfda] bg-white px-4 text-xs font-medium text-[#415049] hover:bg-[#f7faf8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy === "preview" ? "正在生成…" : "生成演变候选"}
          </button>
        </div>

        {preview !== null && (
          <div className="mt-4 space-y-4">
            <div className="whitespace-pre-line rounded-xl border border-[#dfe5e1] bg-[#f9fbf9] px-4 py-3 text-xs leading-relaxed text-[#3b4841]">
              {preview.evolution.summary}
            </div>
            <p className="text-[11px] text-[#8a9690]">
              基于 {preview.feedbackCount} 条反馈 · 当前 v{preview.evolution.baseVersion} · 确认后生成新版本
            </p>

            {preview.adjustments.length === 0 ? (
              <div className="rounded-xl border border-[#eadfc4] bg-[#fbf7ec] px-4 py-3 text-xs leading-relaxed text-[#7b6228]">
                这些反馈没有产生可应用的数值变化，风格保持不变。
              </div>
            ) : (
              <div className="overflow-x-auto rounded-xl border border-[#dfe5e1] bg-white">
                <table className="w-full min-w-[560px] border-collapse text-left text-[11px]">
                  <thead>
                    <tr className="border-b border-[#e4e8e5] text-[10px] uppercase tracking-[0.12em] text-[#8a9a93]">
                      <th className="px-4 py-2 font-medium">字段</th>
                      <th className="px-4 py-2 font-medium">调整前</th>
                      <th className="px-4 py-2 font-medium">调整后</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.adjustments.map((adjustment) => (
                      <tr
                        key={adjustment.field}
                        className="border-b border-[#f0f3f1] align-top"
                      >
                        <td className="px-4 py-2 font-medium text-[#4a574f]">
                          {adjustment.label}
                        </td>
                        <td className="px-4 py-2 text-[#8a9690]">
                          {formatAdjustment(adjustment.before)}
                        </td>
                        <td className="px-4 py-2 text-[#2a3530]">
                          {formatAdjustment(adjustment.after)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {preview.changes.length > 0 && (
              <div className="rounded-xl border border-[#e4e8e5] bg-[#f7f9f7] p-4">
                <h3 className="text-xs font-semibold text-[#55625b]">
                  字段变化（{preview.changes.length}）
                </h3>
                <ul className="mt-2 space-y-1 text-[11px] leading-relaxed text-[#7a8680]">
                  {preview.changes.map((change) => (
                    <li key={change.path}>
                      <span className="font-medium text-[#4a574f]">{change.path}</span>：
                      {formatChangeValue(change.before)} → {formatChangeValue(change.after)}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {preview.limitations.length > 0 && (
              <div className="rounded-xl border border-[#e4e8e5] bg-[#f7f9f7] p-4">
                <h3 className="text-xs font-semibold text-[#55625b]">限制</h3>
                <ul className="mt-2 list-disc space-y-1 pl-4 text-[11px] leading-relaxed text-[#7a8680]">
                  {preview.limitations.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#e4e8e5] pt-4">
              <button
                type="button"
                disabled={disabled}
                onClick={() => void handleDiscard()}
                className="inline-flex min-h-10 items-center rounded-xl px-3 text-xs font-medium text-[#8a3a2e] hover:bg-[#fdf4f2] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50"
              >
                {busy === "discard" ? "正在放弃…" : "放弃候选"}
              </button>
              <button
                type="button"
                disabled={disabled}
                onClick={() => void handleApply()}
                className="inline-flex min-h-11 items-center rounded-xl bg-[#277a68] px-5 text-sm font-medium text-white hover:bg-[#206557] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
              >
                {busy === "apply" ? "正在应用…" : "确认并应用为新版本"}
              </button>
            </div>
          </div>
        )}
      </section>

      <section className="mt-6 rounded-2xl border border-[#dfe5e1] bg-white p-5">
        <h2 className="text-sm font-semibold text-[#202522]">反馈记录</h2>
        {feedbacks.length === 0 ? (
          <p className="mt-3 text-xs text-[#8a9690]">还没有反馈记录。</p>
        ) : (
          <ul className="mt-3 divide-y divide-[#f0f3f1]">
            {feedbacks.map((feedback) => {
              const applied = (feedback.appliedVersion ?? null) !== null;
              return (
                <li key={feedback.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-full border border-[#dbe5e0] bg-[#f4f8f6] px-2 py-0.5 text-[10px] font-medium text-[#365148]">
                        {FEEDBACK_TYPE_LABELS[feedback.feedbackType]}
                      </span>
                      <span className="rounded-full border border-[#e4e8e5] bg-[#f7f9f7] px-2 py-0.5 text-[9px] text-[#6b7a73]">
                        {FEEDBACK_SCOPE_LABELS[feedback.scope]}
                      </span>
                      <span className="text-[9px] text-[#8a9690]">
                        v{feedback.styleVersion} · {formatDateTime(feedback.createdAt)}
                      </span>
                      {applied && (
                        <span className="rounded-full border border-[#bfd5ca] bg-[#f0f7f4] px-2 py-0.5 text-[9px] text-[#277a68]">
                          已应用到 v{feedback.appliedVersion}
                        </span>
                      )}
                    </div>
                    {feedback.note !== null && feedback.note !== undefined && (
                      <p className="mt-1 text-[11px] text-[#5f6d66]">{feedback.note}</p>
                    )}
                  </div>
                  {!applied && (
                    <button
                      type="button"
                      disabled={disabled}
                      onClick={() => void handleDeleteFeedback(feedback)}
                      className="inline-flex min-h-8 items-center rounded-lg px-2.5 text-[11px] font-medium text-[#8a3a2e] hover:bg-[#fdf4f2] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50"
                    >
                      删除
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className="mt-6 rounded-2xl border border-[#dfe5e1] bg-white p-5">
        <h2 className="text-sm font-semibold text-[#202522]">演变历史</h2>
        {evolutions.length === 0 ? (
          <p className="mt-3 text-xs text-[#8a9690]">还没有演变记录。</p>
        ) : (
          <ol className="mt-3 space-y-3">
            {evolutions.map((evolution) => (
              <li key={evolution.id} className="rounded-xl border border-[#e4e8e5] bg-[#f9fbf9] p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full border border-[#dbe5e0] bg-white px-2 py-0.5 text-[10px] font-medium text-[#365148]">
                    {EVOLUTION_STATUS_LABELS[evolution.status]}
                  </span>
                  <span className="text-[10px] text-[#8a9690]">
                    v{evolution.baseVersion}
                    {evolution.newVersion !== null && evolution.newVersion !== undefined
                      ? ` → v${evolution.newVersion}`
                      : ""}
                    {" · "}
                    {formatDateTime(evolution.confirmedAt ?? evolution.createdAt)}
                  </span>
                </div>
                <p className="mt-2 whitespace-pre-line text-[11px] leading-relaxed text-[#5f6d66]">
                  {evolution.reason}
                </p>
              </li>
            ))}
          </ol>
        )}
      </section>
    </main>
  );
}
