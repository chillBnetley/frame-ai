"use client";

import { useId, useState } from "react";

import { GenerativeMaskEditor } from "./generative-mask-editor";
import { generativeMaskImageUrl } from "@/lib/api/generative";
import type { GenerativeMaskView } from "@/types/generative";

export interface GenerativeMaskSelectProps {
  sessionId: string;
  masks: GenerativeMaskView[];
  selectedMaskId: string | null;
  label: string;
  emptyHint: string;
  onSelect: (maskId: string) => void;
  onMaskCreated: (mask: GenerativeMaskView) => void;
  imageUrl?: string | null;
  baseWidth?: number;
  baseHeight?: number;
  coverageLabel?: string;
  kindLabels?: Partial<Record<GenerativeMaskView["kind"], string>>;
}

const DEFAULT_KIND_LABELS: Record<string, string> = {
  brush: "画笔蒙版",
  rect: "矩形框选",
  ellipse: "椭圆框选",
  semantic: "AI 识别区域",
  ai_proposal: "AI 建议区域",
};

export function GenerativeMaskSelect({
  sessionId,
  masks,
  selectedMaskId,
  label,
  emptyHint,
  onSelect,
  onMaskCreated,
  imageUrl = null,
  baseWidth = 1920,
  baseHeight = 1080,
  coverageLabel = "覆盖率",
  kindLabels,
}: GenerativeMaskSelectProps) {
  const groupId = useId();
  const [showEditor, setShowEditor] = useState(false);

  const kindLabel = (kind: GenerativeMaskView["kind"]): string =>
    kindLabels?.[kind] ?? DEFAULT_KIND_LABELS[kind] ?? kind;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <label id={`${groupId}-label`} className="text-xs font-medium text-[#3d4541]">
          {label}
        </label>
        <button
          type="button"
          onClick={() => setShowEditor((prev) => !prev)}
          className="text-xs px-2.5 py-1 rounded bg-[#e7f1ed] hover:bg-[#dceae4] text-[#1f6252] border border-[#c9ded6] transition-colors"
        >
          {showEditor ? "关闭蒙版画板" : "绘制新蒙版"}
        </button>
      </div>

      {showEditor && (
        <div className="border border-[#e4e8e5] rounded-lg p-3 bg-[#ffffff]">
          <GenerativeMaskEditor
            sessionId={sessionId}
            imageUrl={imageUrl}
            previewWidth={Math.min(baseWidth, 640)}
            previewHeight={Math.min(baseHeight, 480)}
            onMaskCreated={(mask) => {
              onMaskCreated(mask);
              setShowEditor(false);
            }}
            onClose={() => setShowEditor(false)}
          />
        </div>
      )}

      {masks.length > 0 ? (
        <div
          role="radiogroup"
          aria-labelledby={`${groupId}-label`}
          className="grid grid-cols-1 sm:grid-cols-2 gap-2"
        >
          {masks.map((mask) => {
            const isSelected = mask.maskId === selectedMaskId;
            return (
              <button
                key={mask.maskId}
                type="button"
                role="radio"
                aria-checked={isSelected}
                onClick={() => onSelect(mask.maskId)}
                className={`flex items-center gap-3 p-2.5 rounded-lg border text-left transition-all ${
                  isSelected
                    ? "bg-[#e7f1ed] border-[#277a68] text-[#163f34] shadow-sm"
                    : "bg-[#ffffff] border-[#dfe4e0] text-[#3d4541] hover:border-[#c3cec8]"
                }`}
              >
                {/* eslint-disable-next-line @next/next/no-img-element -- the API streams the mask PNG */}
                <img
                  src={generativeMaskImageUrl(mask.maskId)}
                  alt=""
                  aria-hidden="true"
                  className="w-12 h-12 object-contain bg-[#eceeec] border border-[#dfe4e0] rounded"
                />
                <div className="flex-1 min-w-0 text-xs">
                  <div className="font-medium truncate">{kindLabel(mask.kind)}</div>
                  <div className="text-[11px] text-[#69716c] mt-0.5">
                    {coverageLabel}: {(mask.quality.coverage * 100).toFixed(1)}%
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      ) : (
        !showEditor && (
          <div className="p-4 text-center rounded-lg border border-dashed border-[#d7dcd8] bg-[#ffffff] text-[#69716c] text-xs">
            <span>{emptyHint}</span>
          </div>
        )
      )}

      {selectedMaskId && (
        <div className="text-[11px] text-[#69716c] bg-[#ffffff] px-3 py-2 rounded border border-[#e4e8e5] flex items-center justify-between">
          <span>当前已选蒙版: {selectedMaskId.slice(0, 8)}...</span>
          <span className="text-[#1f7a52]">已就绪</span>
        </div>
      )}
    </div>
  );
}
