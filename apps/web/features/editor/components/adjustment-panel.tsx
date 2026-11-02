"use client";

import { ADJUSTMENT_RANGES, type NumericAdjustmentKey } from "@/lib/recipe";
import type { Adjustments, Crop } from "@/types/session";

import { SliderField } from "./slider-field";

interface AdjustmentDefinition {
  key: NumericAdjustmentKey;
  label: string;
  unit?: string;
}

interface AdjustmentGroup {
  id: string;
  title: string;
  items: AdjustmentDefinition[];
}

const GROUPS: AdjustmentGroup[] = [
  {
    id: "light",
    title: "光线",
    items: [
      { key: "exposureEv", label: "曝光", unit: "EV" },
      { key: "contrast", label: "对比度" },
      { key: "highlights", label: "高光" },
      { key: "shadows", label: "阴影" },
    ],
  },
  {
    id: "color",
    title: "色彩",
    items: [
      { key: "temperature", label: "色温" },
      { key: "tint", label: "色调" },
      { key: "saturation", label: "饱和度" },
      { key: "vibrance", label: "自然饱和度" },
    ],
  },
  {
    id: "detail",
    title: "细节",
    items: [
      { key: "clarity", label: "清晰度" },
      { key: "sharpen", label: "锐化" },
      { key: "denoise", label: "降噪" },
    ],
  },
  {
    id: "effects",
    title: "效果",
    items: [
      { key: "vignette", label: "暗角" },
      { key: "grain", label: "颗粒" },
    ],
  },
  {
    id: "geometry",
    title: "几何",
    items: [{ key: "rotationDeg", label: "旋转", unit: "°" }],
  },
];

function cropSummary(crop: Crop | null | undefined): string {
  if (!crop) {
    return "全图（未裁切）";
  }
  return `x ${Math.round(crop.x * 100)}% · y ${Math.round(crop.y * 100)}% · 宽 ${Math.round(
    crop.w * 100,
  )}% · 高 ${Math.round(crop.h * 100)}%`;
}

export interface AdjustmentPanelProps {
  adjustments: Adjustments;
  disabled?: boolean;
  onChange: (key: NumericAdjustmentKey, value: number) => void;
  onCommit: () => void;
  onOpenCrop: () => void;
  onClearCrop: () => void;
}

export function AdjustmentPanel({
  adjustments,
  disabled = false,
  onChange,
  onCommit,
  onOpenCrop,
  onClearCrop,
}: AdjustmentPanelProps) {
  const rotation = adjustments.rotationDeg;
  const crop = adjustments.crop ?? null;

  return (
    <section aria-labelledby="adjustment-heading" className="grid gap-5">
      <div className="flex items-center justify-between gap-2">
        <h3 id="adjustment-heading" className="text-sm font-medium text-white">
          手动参数
        </h3>
        <span className="rounded-full border border-white/10 px-2 py-0.5 font-mono text-[9px] uppercase tracking-[0.12em] text-white/35">
          Recipe 1.0
        </span>
      </div>

      {GROUPS.map((group) => (
        <fieldset
          key={group.id}
          disabled={disabled}
          className="grid gap-4 rounded-xl border border-white/8 bg-white/[0.015] p-4"
        >
          <legend className="px-1 font-mono text-[10px] uppercase tracking-[0.16em] text-white/40">
            {group.title}
          </legend>
          {group.items.map((item) => {
            const range = ADJUSTMENT_RANGES[item.key];
            return (
              <div key={item.key}>
                <SliderField
                  label={item.label}
                  value={adjustments[item.key]}
                  min={range.min}
                  max={range.max}
                  step={range.step}
                  defaultValue={range.defaultValue}
                  unit={item.unit}
                  disabled={disabled}
                  onChange={(value) => onChange(item.key, value)}
                  onCommit={onCommit}
                />
                {item.key === "rotationDeg" && (
                  <p
                    className={`mt-1 flex items-start gap-1.5 text-[10px] leading-relaxed ${
                      rotation !== 0 ? "text-amber-200/80" : "text-white/30"
                    }`}
                  >
                    <span aria-hidden="true">△</span>
                    旋转会裁掉边缘：画面会缩放到旋转后的最大内接矩形。
                  </p>
                )}
              </div>
            );
          })}

          {group.id === "geometry" && (
            <div className="grid gap-2 border-t border-white/8 pt-3">
              <p className="text-[11px] text-white/45" id="crop-summary">
                {cropSummary(crop)}
              </p>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={onOpenCrop}
                  disabled={disabled}
                  className="min-h-11 rounded-lg border border-white/12 bg-white/[0.03] px-3 text-xs text-white/70 transition-colors hover:bg-white/[0.07] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40"
                >
                  调整裁切
                </button>
                <button
                  type="button"
                  onClick={onClearCrop}
                  disabled={disabled || crop === null}
                  aria-describedby="crop-summary"
                  className="min-h-11 rounded-lg border border-white/12 px-3 text-xs text-white/55 transition-colors hover:bg-white/[0.05] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40"
                >
                  清除裁切
                </button>
              </div>
            </div>
          )}
        </fieldset>
      ))}
    </section>
  );
}
