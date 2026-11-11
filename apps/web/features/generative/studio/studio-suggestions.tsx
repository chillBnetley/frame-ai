"use client";

import { useId, useState } from "react";

import { SEVERITY_LABELS } from "@/features/analysis/presentation";
import type { GenerativeSuggestion } from "../suggestions";

export interface StudioSuggestionsProps {
  suggestions: GenerativeSuggestion[];
  disabled?: boolean;
  onApply: (suggestion: GenerativeSuggestion) => void;
  onCreateSubjectMask?: (suggestion: GenerativeSuggestion) => Promise<void>;
}

const APPLY_LABELS: Record<string, string> = {
  outpaint: "填入扩图指令",
  remove: "填入消除指令",
  local_edit: "填入局部生成指令",
};

const BUTTON_CLASS =
  "self-start rounded-lg border border-[#d7dcd8] bg-[#ffffff] px-2.5 py-1 text-[11px] text-[#3d4541] transition-colors hover:border-[#277a68]/60 hover:bg-[#eef1ef] hover:text-[#1f6252] disabled:cursor-not-allowed disabled:opacity-50";

export function StudioSuggestions({
  suggestions,
  disabled = false,
  onApply,
  onCreateSubjectMask,
}: StudioSuggestionsProps) {
  const headingId = useId();
  const [maskBusyId, setMaskBusyId] = useState<string | null>(null);
  const [maskError, setMaskError] = useState<string | null>(null);
  if (suggestions.length === 0) {
    return null;
  }
  const generative = suggestions.filter((item) => item.route === "generative");
  const adjustment = suggestions.filter((item) => item.route === "adjustment");

  const createSubjectMask = async (suggestion: GenerativeSuggestion): Promise<void> => {
    if (!onCreateSubjectMask || maskBusyId !== null) {
      return;
    }
    setMaskError(null);
    setMaskBusyId(suggestion.id);
    try {
      await onCreateSubjectMask(suggestion);
    } catch (error: unknown) {
      setMaskError(
        error instanceof Error && error.message
          ? error.message
          : "创建主体蒙版失败，请稍后重试。",
      );
    } finally {
      setMaskBusyId(null);
    }
  };

  return (
    <section
      aria-labelledby={headingId}
      className="flex flex-col gap-2.5 rounded-lg border border-[#e4e8e5] bg-[#ffffff] p-3"
    >
      <div>
        <h3 id={headingId} className="text-xs font-medium text-[#202522]">
          分析建议
        </h3>
        <p className="mt-0.5 text-[11px] leading-relaxed text-[#8a938e]">
          点击只填入参数，不会自动提交生成任务。
        </p>
      </div>

      {generative.length > 0 && (
        <ul className="flex flex-col gap-2">
          {generative.map((item) => (
            <li
              key={item.id}
              className="flex flex-col gap-1.5 rounded-lg border border-[#e4e8e5] bg-[#f6f7f6] p-2.5"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-[#202522]">{item.label}</span>
                <span className="shrink-0 text-[10px] text-[#8a938e]">
                  严重度 {SEVERITY_LABELS[item.severity]}
                </span>
              </div>
              <p className="text-[11px] leading-relaxed text-[#69716c]">{item.evidence}</p>
              {item.subjectLabel && item.subjectBbox && (
                <p className="text-[11px] leading-relaxed text-[#8a938e]">
                  关联主体：{item.subjectLabel}，可据此绘制矩形蒙版。
                </p>
              )}
              <div className="flex flex-wrap items-center gap-1.5">
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => onApply(item)}
                  className={BUTTON_CLASS}
                >
                  {APPLY_LABELS[item.capability ?? "local_edit"]}
                </button>
                {onCreateSubjectMask && item.subjectBbox && (
                  <button
                    type="button"
                    disabled={disabled || maskBusyId !== null}
                    onClick={() => void createSubjectMask(item)}
                    className={BUTTON_CLASS}
                  >
                    {maskBusyId === item.id ? "正在创建蒙版…" : "用主体区域建蒙版"}
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {maskError && (
        <p role="alert" className="text-[11px] leading-relaxed text-[#b42318]">
          {maskError}
        </p>
      )}

      {adjustment.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <h4 className="text-[11px] font-medium text-[#69716c]">建议在参数精修中处理</h4>
          <ul className="flex flex-col gap-1">
            {adjustment.map((item) => (
              <li key={item.id} className="text-[11px] leading-relaxed text-[#8a938e]">
                <span className="text-[#3d4541]">{item.label}</span>
                {` · ${item.advice ?? item.evidence}`}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}