"use client";

import type { RevisionSource, RevisionSummary } from "@/types/session";

const SOURCE_LABELS: Record<RevisionSource, string> = {
  initial: "初始",
  user: "手动",
  ai: "AI",
  reset: "重置",
};

const SOURCE_GLYPHS: Record<RevisionSource, string> = {
  initial: "◆",
  user: "✎",
  ai: "✦",
  reset: "↺",
};

const GENERATIVE_TASK_LABELS: Record<string, string> = {
  outpaint: "扩图",
  remove: "消除",
  local_edit: "局部生成",
  inpaint: "修补",
};


function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

export interface HistoryBarProps {
  canUndo: boolean;
  canRedo: boolean;
  canReset: boolean;
  busy?: boolean;
  items: RevisionSummary[];
  activeRevisionId: string | null;
  onUndo: () => void;
  onRedo: () => void;
  onReset: () => void;
  onActivate: (revisionId: string) => void;
}

const buttonBase =
  "inline-flex min-h-11 items-center justify-center gap-1.5 rounded-lg border border-white/12 bg-white/[0.03] px-3 text-xs text-white/70 transition-colors hover:bg-white/[0.07] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent aria-disabled:cursor-not-allowed aria-disabled:opacity-40 aria-disabled:hover:bg-white/[0.03]";

export function HistoryBar({
  canUndo,
  canRedo,
  canReset,
  busy = false,
  items,
  activeRevisionId,
  onUndo,
  onRedo,
  onReset,
  onActivate,
}: HistoryBarProps) {
  const undoDisabled = !canUndo || busy;
  const redoDisabled = !canRedo || busy;
  const resetDisabled = !canReset || busy;

  const hint =
    undoDisabled && redoDisabled
      ? "没有可撤销或重做的步骤。"
      : undoDisabled
        ? "没有可撤销的步骤，仍可重做。"
        : redoDisabled
          ? "没有可重做的步骤，仍可撤销。"
          : "撤销或重做会切换到对应版本，并重新渲染终稿。";

  return (
    <section
      aria-labelledby="history-heading"
      className="rounded-2xl border border-white/8 bg-black/20 p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="history-heading" className="text-sm font-medium text-white">
          历史与版本
        </h3>
        <p role="status" aria-live="polite" className="text-[10px] text-white/35">
          {busy ? "正在切换版本…" : hint}
        </p>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          aria-disabled={undoDisabled}
          onClick={() => {
            if (!undoDisabled) {
              onUndo();
            }
          }}
          className={buttonBase}
        >
          <span aria-hidden="true">↶</span>
          撤销
        </button>
        <button
          type="button"
          aria-disabled={redoDisabled}
          onClick={() => {
            if (!redoDisabled) {
              onRedo();
            }
          }}
          className={buttonBase}
        >
          <span aria-hidden="true">↷</span>
          重做
        </button>
        <button
          type="button"
          aria-disabled={resetDisabled}
          onClick={() => {
            if (!resetDisabled) {
              onReset();
            }
          }}
          className={buttonBase}
        >
          <span aria-hidden="true">↺</span>
          重置
        </button>
      </div>

      {items.length === 0 ? (
        <p className="mt-3 text-[11px] text-white/35">暂无历史版本。</p>
      ) : (
        <ol className="mt-3 max-h-64 divide-y divide-white/6 overflow-y-auto rounded-xl border border-white/8 bg-white/[0.015]">
          {items.map((item, index) => {
            const older = items[index + 1];
            const isBranch = item.parentId !== null && item.parentId !== older?.id;
            const active = item.id === activeRevisionId;
            return (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => onActivate(item.id)}
                  aria-current={active ? "true" : undefined}
                  className={`flex min-h-11 w-full items-center justify-between gap-3 px-3 py-2 text-left transition-colors hover:bg-white/[0.05] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent ${
                    active ? "bg-accent/[0.08]" : ""
                  }`}
                >
                  <span className="flex min-w-0 items-center gap-2.5">
                    <span
                      aria-hidden="true"
                      className={`font-mono text-[11px] ${
                        active ? "text-accent" : "text-white/40"
                      }`}
                    >
                      {SOURCE_GLYPHS[item.source]}
                    </span>
                    <span className="min-w-0">
                      <span className="flex items-center gap-1.5 text-xs text-white/80">
                        #{item.revisionNo} · {SOURCE_LABELS[item.source]}
                        {item.generative && (
                          <span className="rounded-full border border-sky-400/30 bg-sky-500/10 px-1.5 py-0.5 text-[9px] text-sky-300">
                            {GENERATIVE_TASK_LABELS[item.generative.taskType] ?? item.generative.taskType}
                            {item.generative.isMock ? " · Mock" : ` · ${item.generative.provider}`}
                          </span>
                        )}
                        {active && (
                          <span className="rounded-full border border-accent/30 px-1.5 py-0.5 text-[9px] text-accent">
                            当前
                          </span>
                        )}
                        {isBranch && (
                          <span className="rounded-full border border-white/15 px-1.5 py-0.5 text-[9px] text-white/45">
                            分支
                          </span>
                        )}
                      </span>
                      <span className="mt-0.5 block truncate font-mono text-[9px] text-white/30">
                        {item.generative?.instructionSummary ? `${item.generative.instructionSummary} · ` : ""}
                        {item.id.slice(0, 8)}… · {formatTime(item.createdAt)}
                      </span>
                    </span>
                  </span>
                  <span aria-hidden="true" className="font-mono text-[10px] text-white/25">
                    {active ? "当前" : "切换"}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
