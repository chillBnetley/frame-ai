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
        className="rounded-lg border border-[#f0dfb8] bg-[#fff6e5] px-3 py-2 text-xs text-[#8a5a00]"
      >
        {view.message}
      </p>
    );
  }

  return (
    <div
      role="alert"
      aria-live="assertive"
      className="flex flex-col gap-2 rounded-lg border border-[#f2cbc7] bg-[#fdf2f1] p-3 text-xs"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded border border-[#e9b3ad] bg-[#ffffff] px-1.5 py-0.5 text-[11px] font-medium text-[#b42318]">
          {view.label}
        </span>
        <span className="text-[#8a1c12]">{view.message}</span>
      </div>

      {view.nextStep && (
        <p className="text-[11px] leading-relaxed text-[#a33a2c]">下一步：{view.nextStep}</p>
      )}

      {(view.code || view.requestId) && (
        <p className="font-mono text-[10px] text-[#a9716a]">
          {[view.code, view.requestId ? `请求 ID ${view.requestId}` : null]
            .filter((part): part is string => Boolean(part))
            .join(" · ")}
        </p>
      )}
    </div>
  );
}
