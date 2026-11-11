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
    <div className="flex flex-col gap-3 p-4 bg-[#ffffff] border border-[#e4e8e5] rounded-lg">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-xs font-semibold text-[#202522]">{title}</h3>
        <div className="flex items-center gap-2">
          {badge && (
            <span className="text-[11px] px-2 py-0.5 rounded bg-[#eaf6ef] text-[#1f7a52] border border-[#c4e5d3]">
              {badge}
            </span>
          )}
          <span className="text-[11px] text-[#69716c] font-mono">
            {result.width} × {result.height}
          </span>
        </div>
      </div>

      {/* eslint-disable-next-line @next/next/no-img-element -- the API streams the candidate PNG */}
      <img
        src={generativeResultImageUrl(result.resultId)}
        alt={alt}
        className="max-h-72 w-full object-contain rounded border border-[#e4e8e5] bg-[#eceeec]"
      />

      {result.warnings && result.warnings.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {result.warnings.map((warning) => (
            <span
              key={warning}
              className="text-[10px] px-2 py-0.5 rounded bg-[#f6f7f6] text-[#69716c] border border-[#dfe4e0]"
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
          className="px-3 py-1.5 text-xs rounded-lg border border-[#dfe4e0] text-[#3d4541] hover:bg-[#eef1ef] transition-colors"
        >
          {rejectLabel}
        </button>
        <button
          type="button"
          onClick={() => onAccept(result.resultId)}
          disabled={busy}
          className="px-4 py-1.5 text-xs font-medium rounded-lg bg-[#277a68] hover:bg-[#1f6252] disabled:bg-[#dfe4e0] disabled:text-[#8a938e] text-[#ffffff] shadow-sm transition-colors"
        >
          {busy ? acceptingLabel : acceptLabel}
        </button>
      </div>
    </div>
  );
}
