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
}: OutpaintParamsFormProps) {
  const formId = useId();
  const geometry = computeOutpaintGeometry({
    baseWidth,
    baseHeight,
    margins: values.margins,
    aspectRatio: values.aspectRatio,
    alignment: values.alignment,
  });

  const setMargin = (key: keyof OutpaintMargins, raw: string): void => {
    onChange({
      ...values,
      margins: { ...values.margins, [key]: Math.max(0, Number.parseInt(raw || "0", 10) || 0) },
    });
  };

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2.5">
        <label id={`${formId}-ratio-label`} className="text-xs font-medium text-neutral-300">
          目标画幅比例
        </label>
        <div
          role="radiogroup"
          aria-labelledby={`${formId}-ratio-label`}
          className="grid grid-cols-3 sm:grid-cols-5 gap-2"
        >
          {PRESET_RATIOS.map((item) => {
            const isSelected = values.aspectRatio === item.value;
            return (
              <button
                key={item.label}
                type="button"
                role="radio"
                aria-checked={isSelected}
                disabled={disabled}
                onClick={() => onChange({ ...values, aspectRatio: item.value })}
                className={`py-1.5 px-3 text-xs rounded-lg border transition-all disabled:opacity-50 ${
                  isSelected
                    ? "bg-sky-600 border-sky-400 text-white shadow-sm font-semibold"
                    : "bg-neutral-800/80 border-neutral-700/80 text-neutral-300 hover:bg-neutral-800 hover:border-neutral-600"
                }`}
              >
                {item.label}
              </button>
            );
          })}
        </div>
      </div>

      {values.aspectRatio && (
        <div className="flex flex-col gap-2">
          <label id={`${formId}-align-label`} className="text-xs font-medium text-neutral-300">
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
                      ? "bg-neutral-200 border-white text-neutral-900 font-semibold"
                      : "bg-neutral-800 border-neutral-700 text-neutral-300 hover:bg-neutral-700"
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
          <span className="text-xs font-medium text-neutral-300">自定义各向扩展像素 (px)</span>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
            {MARGIN_FIELDS.map((field) => (
              <div key={field.key}>
                <label
                  htmlFor={`${formId}-${field.key}`}
                  className="text-[11px] text-neutral-400 block mb-1"
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
                  className="w-full bg-neutral-950 border border-neutral-700 rounded px-2.5 py-1 text-xs text-neutral-200 focus:outline-none focus:border-sky-500 disabled:opacity-50"
                />
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="bg-neutral-950/70 border border-neutral-800 rounded-lg p-3 flex flex-col sm:flex-row items-center justify-between gap-4">
        <div className="text-xs space-y-1">
          <div className="text-neutral-400">
            原画尺寸:{" "}
            <span className="text-neutral-200 font-mono">
              {baseWidth} × {baseHeight}
            </span>
          </div>
          <div className="text-neutral-400">
            目标尺寸:{" "}
            <span className="text-sky-400 font-mono font-medium">
              {geometry.targetWidth} × {geometry.targetHeight}
            </span>{" "}
            <span className="text-[11px] text-neutral-500">
              (+{geometry.targetWidth - baseWidth}px 宽, +{geometry.targetHeight - baseHeight}px 高)
            </span>
          </div>
          <div className="text-[11px] text-neutral-500">
            边距: 上 {geometry.top}px · 下 {geometry.bottom}px · 左 {geometry.left}px · 右{" "}
            {geometry.right}px
          </div>
        </div>

        <div
          aria-hidden="true"
          className="relative w-28 h-20 bg-sky-950/40 border border-dashed border-sky-600/40 rounded flex items-center justify-center p-1"
        >
          <div
            className="bg-neutral-700 border border-neutral-500 text-[9px] text-neutral-200 flex items-center justify-center rounded-sm transition-all"
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
