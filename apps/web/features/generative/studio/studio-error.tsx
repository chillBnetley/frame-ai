"use client";

import { describeGenerativeError } from "@/lib/generative-errors";

export interface StudioErrorProps {
  /** Whatever the task controller reported: payload, Error, hint string, or null. */
  error: unknown;
}

export function StudioError({ error }: StudioErrorProps) {
  const view = describeGenerativeError(error);

  if (view === null) {
    return null;
  }

  if (view.category === null) {
    return (
      <p
        role="status"
        className="rounded-lg border border-amber-300/25 bg-amber-300/10 px-3 py-2 text-xs text-amber-200"
      >
        {view.message}
      </p>
    );
  }

  return (
    <div
      role="alert"
      aria-live="assertive"
      className="flex flex-col gap-2 rounded-lg border border-rose-800/50 bg-rose-950/30 p-3 text-xs"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded border border-rose-500/40 bg-rose-500/10 px-1.5 py-0.5 text-[11px] font-medium text-rose-200">
          {view.label}
        </span>
        <span className="text-rose-100">{view.message}</span>
      </div>

      {view.nextStep && (
        <p className="text-[11px] leading-relaxed text-rose-200/85">下一步：{view.nextStep}</p>
      )}

      {(view.code || view.requestId) && (
        <p className="font-mono text-[10px] text-rose-200/55">
          {[view.code, view.requestId ? `请求 ID ${view.requestId}` : null]
            .filter((part): part is string => Boolean(part))
            .join(" · ")}
        </p>
      )}
    </div>
  );
}
