"use client";

import { generativeResultImageUrl } from "@/lib/api/generative";
import type { GenerativeResultView } from "@/types/generative";

export interface GenerativeTaskResultProps {
  result: GenerativeResultView;
  title: string;
  alt: string;
  acceptLabel: string;
  acceptingLabel: string;
  badge?: string | null;
  rejectLabel?: string;
  busy?: boolean;
  onAccept: (resultId: string) => void;
  onReject: (resultId: string) => void;
}

export function GenerativeTaskResult({
  result,
  title,
  alt,
  acceptLabel,
  acceptingLabel,
  badge = null,
  rejectLabel = "放弃",
  busy = false,
  onAccept,
  onReject,
}: GenerativeTaskResultProps) {
  return (
    <div className="flex flex-col gap-3 p-4 bg-neutral-950 border border-neutral-800 rounded-lg">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-xs font-semibold text-neutral-200">{title}</h3>
        <div className="flex items-center gap-2">
          {badge && (
            <span className="text-[11px] px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              {badge}
            </span>
          )}
          <span className="text-[11px] text-neutral-400 font-mono">
            {result.width} × {result.height}
          </span>
        </div>
      </div>

      {/* eslint-disable-next-line @next/next/no-img-element -- the API streams the candidate PNG */}
      <img
        src={generativeResultImageUrl(result.resultId)}
        alt={alt}
        className="max-h-72 w-full object-contain rounded border border-neutral-800 bg-neutral-900"
      />

      {result.warnings && result.warnings.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {result.warnings.map((warning) => (
            <span
              key={warning}
              className="text-[10px] px-2 py-0.5 rounded bg-neutral-800 text-neutral-300 border border-neutral-700"
            >
              {warning}
            </span>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-2 justify-end">
        <button
          type="button"
          onClick={() => onReject(result.resultId)}
          className="px-3 py-1.5 text-xs rounded-lg border border-neutral-700 text-neutral-300 hover:bg-neutral-800 transition-colors"
        >
          {rejectLabel}
        </button>
        <button
          type="button"
          onClick={() => onAccept(result.resultId)}
          disabled={busy}
          className="px-4 py-1.5 text-xs font-medium rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:bg-neutral-800 disabled:text-neutral-500 text-white shadow-sm transition-colors"
        >
          {busy ? acceptingLabel : acceptLabel}
        </button>
      </div>
    </div>
  );
}
