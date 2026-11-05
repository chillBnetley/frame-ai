"use client";

import { useId, useState } from "react";

import { SliderField } from "./slider-field";
import { COLOR_GRADING_RANGES } from "@/lib/recipe";
import type { ColorGradeZone, ColorGradeZoneName, ColorGrading } from "@/types/session";

interface ZoneDefinition {
  id: ColorGradeZoneName;
  label: string;
}

const ZONES: readonly ZoneDefinition[] = [
  { id: "shadows", label: "阴影" },
  { id: "midtones", label: "中间调" },
  { id: "highlights", label: "高光" },
];

function zoneIsEdited(zone: ColorGradeZone): boolean {
  return zone.saturation > 0;
}

function swatchColor(zone: ColorGradeZone): string {
  if (zone.saturation <= 0) {
    return "transparent";
  }
  return `hsl(${zone.hue} 85% 55%)`;
}

export interface ColorGradingPanelProps {
  grading: Required<ColorGrading>;
  disabled?: boolean;
  onChange: (zone: ColorGradeZoneName, key: keyof ColorGradeZone, value: number) => void;
  onOptionChange: (key: "balance" | "blending", value: number) => void;
  onResetZone: (zone: ColorGradeZoneName) => void;
  onResetAll: () => void;
  onCommit: () => void;
}

export function ColorGradingPanel({
  grading,
  disabled = false,
  onChange,
  onOptionChange,
  onResetZone,
  onResetAll,
  onCommit,
}: ColorGradingPanelProps) {
  const headingId = useId();
  const hintId = useId();
  const [activeZone, setActiveZone] = useState<ColorGradeZoneName>("shadows");
  const activeOption = ZONES.find((zone) => zone.id === activeZone) ?? ZONES[0];
  const active = grading[activeZone];
  const activeEdited = zoneIsEdited(active);
  const anyEdited = ZONES.some((zone) => zoneIsEdited(grading[zone.id]));

  return (
    <section
      aria-labelledby={headingId}
      aria-describedby={hintId}
      className="grid gap-3 rounded-xl border border-white/8 bg-white/[0.015] p-4"
    >
      <div className="flex items-center justify-between gap-2">
        <h4 id={headingId} className="text-xs font-medium text-white/80">
          颜色分级
        </h4>
        <span className="font-mono text-[9px] uppercase tracking-[0.12em] text-white/30">
          3 Zones
        </span>
      </div>

      <div role="group" aria-label="颜色分级区域" className="grid grid-cols-3 gap-1">
        {ZONES.map((zone) => {
          const isActive = zone.id === activeZone;
          return (
            <button
              key={zone.id}
              type="button"
              aria-pressed={isActive}
              disabled={disabled}
              onClick={() => setActiveZone(zone.id)}
              data-testid={`grading-zone-${zone.id}`}
              className={`min-h-9 rounded-md border px-1 text-[11px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40 ${
                isActive
                  ? "border-white/25 bg-white/10 text-white"
                  : "border-white/10 bg-black/20 text-white/55 hover:bg-white/[0.06] hover:text-white"
              }`}
            >
              <span
                aria-hidden="true"
                data-testid={`grading-swatch-${zone.id}`}
                className="mr-1 inline-block size-1.5 rounded-full align-middle ring-1 ring-white/20"
                style={{ backgroundColor: swatchColor(grading[zone.id]) }}
              />
              {zone.label}
            </button>
          );
        })}
      </div>

      <div className="grid gap-4">
        <SliderField
          key={`${activeZone}-hue`}
          label={`${activeOption.label} 色相`}
          value={active.hue}
          min={COLOR_GRADING_RANGES.hue.min}
          max={COLOR_GRADING_RANGES.hue.max}
          step={COLOR_GRADING_RANGES.hue.step}
          defaultValue={COLOR_GRADING_RANGES.hue.defaultValue}
          unit="°"
          disabled={disabled}
          onChange={(value) => onChange(activeZone, "hue", value)}
          onCommit={onCommit}
        />
        <SliderField
          key={`${activeZone}-saturation`}
          label={`${activeOption.label} 强度`}
          value={active.saturation}
          min={COLOR_GRADING_RANGES.saturation.min}
          max={COLOR_GRADING_RANGES.saturation.max}
          step={COLOR_GRADING_RANGES.saturation.step}
          defaultValue={COLOR_GRADING_RANGES.saturation.defaultValue}
          disabled={disabled}
          onChange={(value) => onChange(activeZone, "saturation", value)}
          onCommit={onCommit}
        />
        <SliderField
          label="平衡"
          value={grading.balance}
          min={COLOR_GRADING_RANGES.balance.min}
          max={COLOR_GRADING_RANGES.balance.max}
          step={COLOR_GRADING_RANGES.balance.step}
          defaultValue={COLOR_GRADING_RANGES.balance.defaultValue}
          disabled={disabled}
          onChange={(value) => onOptionChange("balance", value)}
          onCommit={onCommit}
        />
        <SliderField
          label="混合范围"
          value={grading.blending}
          min={COLOR_GRADING_RANGES.blending.min}
          max={COLOR_GRADING_RANGES.blending.max}
          step={COLOR_GRADING_RANGES.blending.step}
          defaultValue={COLOR_GRADING_RANGES.blending.defaultValue}
          disabled={disabled}
          onChange={(value) => onOptionChange("blending", value)}
          onCommit={onCommit}
        />
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={disabled || !activeEdited}
          onClick={() => onResetZone(activeZone)}
          className="min-h-9 rounded-lg border border-white/12 px-2.5 text-[11px] text-white/60 transition-colors hover:bg-white/[0.06] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-35"
        >
          重置当前区域
        </button>
        <button
          type="button"
          disabled={disabled || !anyEdited}
          onClick={onResetAll}
          className="min-h-9 rounded-lg border border-white/12 px-2.5 text-[11px] text-white/60 transition-colors hover:bg-white/[0.06] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-35"
        >
          重置全部分级
        </button>
      </div>

      <p id={hintId} className="text-[10px] leading-relaxed text-white/30">
        按亮度平滑分配阴影、中间调与高光；强度为 0 时不改变画面。平衡移动区域分界，混合范围控制过渡宽度。
      </p>
    </section>
  );
}
