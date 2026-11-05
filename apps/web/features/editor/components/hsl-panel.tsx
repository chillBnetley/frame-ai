"use client";

import { useId, useState } from "react";

import { SliderField } from "./slider-field";
import { HSL_RANGES } from "@/lib/recipe";
import type { HslAdjustments, HslBand, HslBandName } from "@/types/session";

interface BandDefinition {
  id: HslBandName;
  label: string;
  color: string;
  range: string;
}

interface SliderDefinition {
  key: keyof HslBand;
  label: string;
  unit?: string;
}

const BANDS: readonly BandDefinition[] = [
  { id: "red", label: "红色", color: "#fb7185", range: "330°–30°" },
  { id: "orange", label: "橙色", color: "#fb923c", range: "0°–60°" },
  { id: "yellow", label: "黄色", color: "#facc15", range: "30°–120°" },
  { id: "green", label: "绿色", color: "#4ade80", range: "60°–180°" },
  { id: "aqua", label: "青色", color: "#2dd4bf", range: "120°–240°" },
  { id: "blue", label: "蓝色", color: "#60a5fa", range: "180°–285°" },
  { id: "purple", label: "紫色", color: "#a78bfa", range: "240°–330°" },
  { id: "magenta", label: "洋红", color: "#f472b6", range: "285°–30°" },
];

const SLIDERS: readonly SliderDefinition[] = [
  { key: "hue", label: "色相", unit: "°" },
  { key: "saturation", label: "饱和度" },
  { key: "luminance", label: "明度" },
];

export interface HslPanelProps {
  hsl: Required<HslAdjustments>;
  disabled?: boolean;
  onChange: (band: HslBandName, key: keyof HslBand, value: number) => void;
  onResetBand: (band: HslBandName) => void;
  onResetAll: () => void;
  onCommit: () => void;
}

function bandIsEdited(band: HslBand): boolean {
  return band.hue !== 0 || band.saturation !== 0 || band.luminance !== 0;
}

export function HslPanel({
  hsl,
  disabled = false,
  onChange,
  onResetBand,
  onResetAll,
  onCommit,
}: HslPanelProps) {
  const headingId = useId();
  const hintId = useId();
  const [activeBand, setActiveBand] = useState<HslBandName>("red");
  const activeOption = BANDS.find((option) => option.id === activeBand) ?? BANDS[0];
  const active = hsl[activeBand];
  const activeEdited = bandIsEdited(active);
  const anyEdited = BANDS.some((option) => bandIsEdited(hsl[option.id]));

  return (
    <section
      aria-labelledby={headingId}
      aria-describedby={hintId}
      className="grid gap-3 rounded-xl border border-white/8 bg-white/[0.015] p-4"
    >
      <div className="flex items-center justify-between gap-2">
        <h4 id={headingId} className="text-xs font-medium text-white/80">
          HSL 色彩
        </h4>
        <span className="font-mono text-[9px] uppercase tracking-[0.12em] text-white/30">
          8 Bands
        </span>
      </div>

      <div role="group" aria-label="HSL 色带" className="grid grid-cols-4 gap-1">
        {BANDS.map((option) => {
          const isActive = option.id === activeBand;
          const edited = bandIsEdited(hsl[option.id]);
          return (
            <button
              key={option.id}
              type="button"
              aria-pressed={isActive}
              disabled={disabled}
              title={`${option.label}有效范围 ${option.range}`}
              onClick={() => setActiveBand(option.id)}
              data-testid={`hsl-band-${option.id}`}
              className={`min-h-9 rounded-md border px-1 text-[11px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40 ${
                isActive
                  ? "border-white/25 bg-white/10 text-white"
                  : "border-white/10 bg-black/20 text-white/55 hover:bg-white/[0.06] hover:text-white"
              }`}
            >
              <span
                aria-hidden="true"
                className="mr-1 inline-block size-1.5 rounded-full align-middle"
                style={{ backgroundColor: edited ? option.color : "transparent" }}
              />
              {option.label}
            </button>
          );
        })}
      </div>

      <div className="grid gap-4">
        {SLIDERS.map((item) => {
          const range = HSL_RANGES[item.key];
          return (
            <SliderField
              key={`${activeBand}-${item.key}`}
              label={`${activeOption.label} ${item.label}`}
              value={active[item.key]}
              min={range.min}
              max={range.max}
              step={range.step}
              defaultValue={range.defaultValue}
              unit={item.unit}
              disabled={disabled}
              onChange={(value) => onChange(activeBand, item.key, value)}
              onCommit={onCommit}
            />
          );
        })}
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={disabled || !activeEdited}
          onClick={() => onResetBand(activeBand)}
          className="min-h-9 rounded-lg border border-white/12 px-2.5 text-[11px] text-white/60 transition-colors hover:bg-white/[0.06] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-35"
        >
          重置当前色带
        </button>
        <button
          type="button"
          disabled={disabled || !anyEdited}
          onClick={onResetAll}
          className="min-h-9 rounded-lg border border-white/12 px-2.5 text-[11px] text-white/60 transition-colors hover:bg-white/[0.06] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-35"
        >
          重置全部 HSL
        </button>
      </div>

      <p id={hintId} className="text-[10px] leading-relaxed text-white/30">
        相邻色带平滑过渡；参数为 0 时不改变画面，灰色与接近无彩色的像素不受影响。
      </p>
    </section>
  );
}
