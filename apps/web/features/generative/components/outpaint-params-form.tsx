"use client";

import { useId } from "react";

import { computeOutpaintGeometry, type OutpaintMargins } from "@/lib/generative-canvas";
import type { GenerativeOutpaintAlignment } from "@/types/generative";

export interface OutpaintFormValues {
  aspectRatio: string | null;
  alignment: GenerativeOutpaintAlignment;
  margins: OutpaintMargins;
}

export interface OutpaintParamsFormProps {
  values: OutpaintFormValues;
  onChange: (next: OutpaintFormValues) => void;
  baseWidth: number;
  baseHeight: number;
  disabled?: boolean;
  /** Real providers cap how far a single side may expand; mock leaves it null. */
  maxOutpaintScale?: number | null;
}

const PRESET_RATIOS: { label: string; value: string | null }[] = [
  { label: "自由边距", value: null },
  { label: "1:1", value: "1:1" },
  { label: "16:9", value: "16:9" },
  { label: "9:16", value: "9:16" },
  { label: "4:3", value: "4:3" },
  { label: "3:4", value: "3:4" },
  { label: "3:2", value: "3:2" },
  { label: "2:3", value: "2:3" },
  { label: "21:9", value: "21:9" },
];

const ALIGNMENTS: { label: string; value: GenerativeOutpaintAlignment }[] = [
  { label: "居中", value: "center" },
  { label: "靠上", value: "top" },
  { label: "靠下", value: "bottom" },
  { label: "靠左", value: "left" },
  { label: "靠右", value: "right" },
];

const MARGIN_FIELDS: { key: keyof OutpaintMargins; label: string }[] = [
  { key: "top", label: "向上扩展 (Top)" },
  { key: "bottom", label: "向下扩展 (Bottom)" },
  { key: "left", label: "向左扩展 (Left)" },
  { key: "right", label: "向右扩展 (Right)" },
];

export function OutpaintParamsForm({
  values,
  onChange,
  baseWidth,
  baseHeight,
  disabled = false,
  maxOutpaintScale = null,
}: OutpaintParamsFormProps) {
  const formId = useId();
  const geometry = computeOutpaintGeometry({
    baseWidth,
    baseHeight,
    margins: values.margins,
    aspectRatio: values.aspectRatio,
    alignment: values.alignment,
  });

  const scaleFor = (aspectRatio: string | null): number => {
    const preset = computeOutpaintGeometry({
      baseWidth,
      baseHeight,
      margins: values.margins,
      aspectRatio,
      alignment: values.alignment,
    });
    return Math.max(preset.targetWidth / baseWidth, preset.targetHeight / baseHeight);
  };

  const exceedsLimit = (aspectRatio: string | null): boolean =>
    maxOutpaintScale !== null && scaleFor(aspectRatio) > maxOutpaintScale + 1e-6;

  const currentScale = Math.max(geometry.targetWidth / baseWidth, geometry.targetHeight / baseHeight);
  const currentExceeds = maxOutpaintScale !== null && currentScale > maxOutpaintScale + 1e-6;

  const setMargin = (key: keyof OutpaintMargins, raw: string): void => {
    onChange({
      ...values,
      margins: { ...values.margins, [key]: Math.max(0, Number.parseInt(raw || "0", 10) || 0) },
    });
  };

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2.5">
        <label id={`${formId}-ratio-label`} className="text-xs font-medium text-[#3d4541]">
          目标画幅比例
        </label>
        <div
          role="radiogroup"
          aria-labelledby={`${formId}-ratio-label`}
          className="grid grid-cols-3 gap-2"
        >
          {PRESET_RATIOS.map((item) => {
            const isSelected = values.aspectRatio === item.value;
            const blocked = exceedsLimit(item.value);
            return (
              <button
                key={item.label}
                type="button"
                role="radio"
                aria-checked={isSelected}
                disabled={disabled || blocked}
                title={blocked ? `当前模型每边最多扩 ${maxOutpaintScale}×` : undefined}
                onClick={() => onChange({ ...values, aspectRatio: item.value })}
                className={`whitespace-nowrap py-1.5 px-1.5 text-[11px] rounded-lg border transition-all disabled:opacity-50 ${
                  isSelected
                    ? "bg-[#277a68] border-[#277a68] text-[#ffffff] shadow-sm font-semibold"
                    : "bg-[#ffffff] border-[#dfe4e0] text-[#3d4541] hover:border-[#c3cec8] hover:bg-[#eef1ef]"
                }`}
              >
                {item.label}
              </button>
            );
          })}
        </div>
        {maxOutpaintScale !== null && (
          <p className="text-[11px] text-[#8a938e]">
            当前模型每边最多扩 {maxOutpaintScale}×，超出倍数的比例已禁用。
          </p>
        )}
      </div>

      {values.aspectRatio && (
        <div className="flex flex-col gap-2">
          <label id={`${formId}-align-label`} className="text-xs font-medium text-[#3d4541]">
            画面对齐定位
          </label>
          <div
            role="radiogroup"
            aria-labelledby={`${formId}-align-label`}
            className="flex flex-wrap gap-2"
          >
            {ALIGNMENTS.map((item) => {
              const isSelected = values.alignment === item.value;
              return (
                <button
                  key={item.value}
                  type="button"
                  role="radio"
                  aria-checked={isSelected}
                  disabled={disabled}
                  onClick={() => onChange({ ...values, alignment: item.value })}
                  className={`py-1 px-3 text-xs rounded-md border transition-colors disabled:opacity-50 ${
                    isSelected
                      ? "bg-[#277a68] border-[#277a68] text-[#ffffff] font-semibold"
                      : "bg-[#ffffff] border-[#dfe4e0] text-[#3d4541] hover:bg-[#eef1ef]"
                  }`}
                >
                  {item.label}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {!values.aspectRatio && (
        <div className="flex flex-col gap-2">
          <span className="text-xs font-medium text-[#3d4541]">自定义各向扩展像素 (px)</span>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
            {MARGIN_FIELDS.map((field) => (
              <div key={field.key}>
                <label
                  htmlFor={`${formId}-${field.key}`}
                  className="text-[11px] text-[#69716c] block mb-1"
                >
                  {field.label}
                </label>
                <input
                  id={`${formId}-${field.key}`}
                  type="number"
                  min={0}
                  max={4000}
                  disabled={disabled}
                  value={values.margins[field.key]}
                  onChange={(event) => setMargin(field.key, event.target.value)}
                  className="w-full bg-[#ffffff] border border-[#d7dcd8] rounded px-2.5 py-1 text-xs text-[#202522] focus:outline-none focus:border-[#277a68] focus:ring-1 focus:ring-[#277a68]/30 disabled:opacity-50"
                />
              </div>
            ))}
          </div>
          {currentExceeds && (
            <p className="text-[11px] text-[#b42318]">
              当前边距超过模型每边 {maxOutpaintScale}× 的上限，提交会被拒绝。
            </p>
          )}
        </div>
      )}

      <div className="bg-[#ffffff] border border-[#e4e8e5] rounded-lg p-3 flex flex-col sm:flex-row items-center justify-between gap-4">
        <div className="text-xs space-y-1">
          <div className="text-[#69716c]">
            原画尺寸:{" "}
            <span className="text-[#202522] font-mono">
              {baseWidth} × {baseHeight}
            </span>
          </div>
          <div className="text-[#69716c]">
            目标尺寸:{" "}
            <span className="text-[#1f6252] font-mono font-medium">
              {geometry.targetWidth} × {geometry.targetHeight}
            </span>{" "}
            <span className="text-[11px] text-[#8a938e]">
              (+{geometry.targetWidth - baseWidth}px 宽, +{geometry.targetHeight - baseHeight}px 高)
            </span>
          </div>
          <div className="text-[11px] text-[#8a938e]">
            边距: 上 {geometry.top}px · 下 {geometry.bottom}px · 左 {geometry.left}px · 右{" "}
            {geometry.right}px
          </div>
        </div>

        <div
          aria-hidden="true"
          className="relative w-28 h-20 bg-[#e7f1ed] border border-dashed border-[#277a68]/45 rounded flex items-center justify-center p-1"
        >
          <div
            className="bg-[#ffffff] border border-[#c3cec8] text-[9px] text-[#3d4541] flex items-center justify-center rounded-sm transition-all"
            style={{
              width: `${Math.max(20, Math.min(100, (baseWidth / geometry.targetWidth) * 100))}%`,
              height: `${Math.max(20, Math.min(100, (baseHeight / geometry.targetHeight) * 100))}%`,
            }}
          >
            原图
          </div>
        </div>
      </div>
    </div>
  );
}
