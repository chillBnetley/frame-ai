"use client";

import { useId, useState } from "react";

import { roundTo2 } from "@/lib/recipe";

export interface SliderFieldProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  defaultValue: number;
  unit?: string;
  disabled?: boolean;
  onChange: (value: number) => void;
  onCommit: () => void;
}

const COMMIT_KEYS = new Set([
  "ArrowLeft",
  "ArrowRight",
  "ArrowUp",
  "ArrowDown",
  "Home",
  "End",
  "PageUp",
  "PageDown",
]);

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function formatValue(value: number, step: number): string {
  return step < 1 ? value.toFixed(2) : String(Math.round(value));
}

export function adjustmentValueText(
  value: number,
  step: number,
  unit?: string,
): string {
  const sign = value > 0 ? "+" : "";
  const formatted = `${sign}${formatValue(value, step)}`;
  return unit ? `${formatted} ${unit}` : formatted;
}

export function SliderField({
  label,
  value,
  min,
  max,
  step,
  defaultValue,
  unit,
  disabled = false,
  onChange,
  onCommit,
}: SliderFieldProps) {
  const baseId = useId();
  const labelId = `${baseId}-label`;
  const rangeId = `${baseId}-range`;
  const numberId = `${baseId}-number`;
  const [text, setText] = useState<string | null>(null);

  const apply = (raw: number) => {
    if (!Number.isFinite(raw)) {
      return;
    }
    onChange(roundTo2(clamp(raw, min, max)));
  };

  const commitNumber = () => {
    if (text !== null) {
      const parsed = Number.parseFloat(text);
      setText(null);
      if (Number.isFinite(parsed)) {
        apply(parsed);
      }
    }
    onCommit();
  };

  return (
    <div className="slider-field grid gap-2">
      <div className="flex items-baseline justify-between gap-3">
        <label id={labelId} htmlFor={rangeId} className="text-xs text-white/65">
          {label}
        </label>
        <div className="flex items-center gap-1.5">
          <input
            id={numberId}
            type="number"
            inputMode="decimal"
            min={min}
            max={max}
            step={step}
            value={text ?? formatValue(value, step)}
            disabled={disabled}
            aria-labelledby={labelId}
            onChange={(event) => {
              const raw = event.target.value;
              setText(raw);
              const parsed = Number.parseFloat(raw);
              if (Number.isFinite(parsed)) {
                apply(parsed);
              }
            }}
            onBlur={commitNumber}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                commitNumber();
              }
            }}
            className="min-h-11 w-20 rounded-md border border-white/12 bg-black/35 px-2 py-1.5 text-right font-mono text-[11px] text-white/80 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40"
          />
          {unit && (
            <span aria-hidden="true" className="w-5 font-mono text-[10px] text-white/35">
              {unit}
            </span>
          )}
        </div>
      </div>

      <input
        id={rangeId}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        aria-labelledby={labelId}
        aria-valuetext={adjustmentValueText(value, step, unit)}
        onChange={(event) => apply(Number(event.target.value))}
        onPointerUp={onCommit}
        onKeyUp={(event) => {
          if (COMMIT_KEYS.has(event.key)) {
            onCommit();
          }
        }}
        onBlur={onCommit}
        onDoubleClick={() => {
          apply(defaultValue);
          onCommit();
        }}
        title="双击恢复默认值"
        className="h-11 w-full cursor-pointer accent-[#d8ff5f] disabled:cursor-not-allowed disabled:opacity-40"
      />

      <div className="flex items-center justify-between font-mono text-[9px] text-white/25">
        <span>{formatValue(min, step)}</span>
        <span>双击复位</span>
        <span>{formatValue(max, step)}</span>
      </div>
    </div>
  );
}
