"use client";

import type { GenerativeTaskStage } from "@/types/generative";

export interface GenerativeTaskStatusProps {
  stage: GenerativeTaskStage;
  labels: Record<string, string>;
  onCancel: () => void;
  cancelLabel?: string;
}

/**
 * Stage strip for a running generative task. Only the real backend stage is
 * shown: there is no progress percentage because providers do not report one.
 */
export function GenerativeTaskStatus({
  stage,
  labels,
  onCancel,
  cancelLabel = "取消",
}: GenerativeTaskStatusProps) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex flex-col gap-2 p-3 bg-sky-950/30 border border-sky-800/60 rounded-lg text-xs text-sky-200"
    >
      <div className="flex items-center justify-between gap-3">
        <span className="font-medium animate-pulse">{labels[stage] || "任务执行中..."}</span>
        <button
          type="button"
          onClick={onCancel}
          className="text-xs px-2 py-0.5 rounded bg-neutral-800 hover:bg-neutral-700 text-neutral-300 transition-colors"
        >
          {cancelLabel}
        </button>
      </div>
      <div
        aria-hidden="true"
        className="w-full bg-neutral-800 rounded-full h-1.5 overflow-hidden"
      >
        <div className="bg-sky-500 h-1.5 rounded-full animate-indeterminate" />
      </div>
    </div>
  );
}
