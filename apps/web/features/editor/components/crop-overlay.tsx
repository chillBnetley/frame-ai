"use client";

import { useId, useRef, useState } from "react";
import type {
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
} from "react";

import { roundTo2 } from "@/lib/recipe";
import type { Crop } from "@/types/session";

const FULL_CROP: Crop = { x: 0, y: 0, w: 1, h: 1 };

type CropField = keyof Crop;
type DragMode = "move" | "resize";

interface DragState {
  mode: DragMode;
  startX: number;
  startY: number;
  start: Crop;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function normalize(next: Crop): Crop {
  return {
    x: roundTo2(clamp(next.x, 0, 1)),
    y: roundTo2(clamp(next.y, 0, 1)),
    w: roundTo2(clamp(next.w, 0.01, 1)),
    h: roundTo2(clamp(next.h, 0.01, 1)),
  };
}

function validate(next: Crop): string | null {
  if (roundTo2(next.x + next.w) > 1) {
    return "裁切框超出右边界：x + 宽 不能大于 1。";
  }
  if (roundTo2(next.y + next.h) > 1) {
    return "裁切框超出下边界：y + 高 不能大于 1。";
  }
  return null;
}

interface CropNumberFieldProps {
  label: string;
  value: number;
  disabled: boolean;
  onCandidate: (value: number) => void;
}

function CropNumberField({ label, value, disabled, onCandidate }: CropNumberFieldProps) {
  const id = useId();
  const [text, setText] = useState<string | null>(null);

  return (
    <div className="grid gap-1">
      <label htmlFor={id} className="text-[10px] text-white/45">
        {label}
      </label>
      <input
        id={id}
        type="number"
        inputMode="decimal"
        min={0}
        max={1}
        step={0.01}
        value={text ?? value.toFixed(2)}
        disabled={disabled}
        onChange={(event) => {
          const raw = event.target.value;
          setText(raw);
          const parsed = Number.parseFloat(raw);
          if (Number.isFinite(parsed)) {
            onCandidate(roundTo2(clamp(parsed, 0, 1)));
          }
        }}
        onBlur={() => setText(null)}
        className="w-full rounded-md border border-white/12 bg-black/35 px-2 py-1.5 font-mono text-[11px] text-white/80 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40"
      />
    </div>
  );
}

export interface CropOverlayProps {
  imageUrl: string;
  canvasWidth: number;
  canvasHeight: number;
  crop: Crop | null;
  disabled?: boolean;
  onChange: (crop: Crop | null) => void;
  onApply: () => void;
  onCancel: () => void;
}

export function CropOverlay({
  imageUrl,
  canvasWidth,
  canvasHeight,
  crop,
  disabled = false,
  onChange,
  onApply,
  onCancel,
}: CropOverlayProps) {
  const current = crop ?? FULL_CROP;
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<DragState | null>(null);

  const updateCrop = (next: Crop) => {
    const normalized = normalize(next);
    const message = validate(normalized);
    setError(message);
    if (message === null) {
      onChange(normalized);
    }
  };

  const updateField = (field: CropField, value: number) => {
    const next = { ...current, [field]: value };
    if (field === "w" || field === "h") {
      next[field] = Math.max(0.01, value);
    }
    updateCrop(next);
  };

  const beginDrag = (event: ReactPointerEvent<HTMLElement>, mode: DragMode) => {
    if (disabled) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    dragRef.current = {
      mode,
      startX: event.clientX,
      startY: event.clientY,
      start: current,
    };
  };

  const startMove = (event: ReactPointerEvent<HTMLElement>) => beginDrag(event, "move");
  const startResize = (event: ReactPointerEvent<HTMLElement>) => beginDrag(event, "resize");

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    const rect = containerRef.current?.getBoundingClientRect();
    if (!drag || !rect || rect.width === 0 || rect.height === 0) {
      return;
    }
    const dx = (event.clientX - drag.startX) / rect.width;
    const dy = (event.clientY - drag.startY) / rect.height;
    if (drag.mode === "move") {
      updateCrop({
        ...drag.start,
        x: roundTo2(clamp(drag.start.x + dx, 0, 1 - drag.start.w)),
        y: roundTo2(clamp(drag.start.y + dy, 0, 1 - drag.start.h)),
      });
    } else {
      updateCrop({
        ...drag.start,
        w: roundTo2(clamp(drag.start.w + dx, 0.01, 1 - drag.start.x)),
        h: roundTo2(clamp(drag.start.h + dy, 0.01, 1 - drag.start.y)),
      });
    }
  };

  const endDrag = () => {
    dragRef.current = null;
  };

  const nudge = (mode: DragMode) => (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (disabled) {
      return;
    }
    const step = event.shiftKey ? 0.05 : 0.01;
    const next = { ...current };
    if (mode === "move") {
      if (event.key === "ArrowLeft") next.x = clamp(next.x - step, 0, 1 - next.w);
      else if (event.key === "ArrowRight") next.x = clamp(next.x + step, 0, 1 - next.w);
      else if (event.key === "ArrowUp") next.y = clamp(next.y - step, 0, 1 - next.h);
      else if (event.key === "ArrowDown") next.y = clamp(next.y + step, 0, 1 - next.h);
      else return;
    } else {
      if (event.key === "ArrowLeft") next.w = clamp(next.w - step, 0.01, 1 - next.x);
      else if (event.key === "ArrowRight") next.w = clamp(next.w + step, 0.01, 1 - next.x);
      else if (event.key === "ArrowUp") next.h = clamp(next.h - step, 0.01, 1 - next.y);
      else if (event.key === "ArrowDown") next.h = clamp(next.h + step, 0.01, 1 - next.y);
      else return;
    }
    event.preventDefault();
    updateCrop(next);
  };

  return (
    <section aria-labelledby="crop-heading" className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h4 id="crop-heading" className="text-xs font-medium text-white/80">
            裁切
          </h4>
          <p className="mt-0.5 text-[10px] text-white/35">
            坐标基于旋转内接后的画布（{canvasWidth} × {canvasHeight}），归一化范围 0–1。
          </p>
        </div>
        <span className="rounded-full border border-white/10 px-2 py-0.5 font-mono text-[9px] text-white/35">
          x + 宽 ≤ 1
        </span>
      </div>

      <div
        ref={containerRef}
        className="relative overflow-hidden rounded-xl bg-black ring-1 ring-white/10"
        style={{ aspectRatio: `${canvasWidth} / ${canvasHeight}` }}
        onPointerMove={handlePointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- content-addressed previews are served by the API */}
        <img
          src={imageUrl}
          alt="裁切基准画面"
          className="absolute inset-0 h-full w-full object-fill"
          draggable={false}
        />
        <div
          className="absolute border-2 border-accent shadow-[0_0_0_9999px_rgba(0,0,0,0.45)]"
          style={{
            left: `${current.x * 100}%`,
            top: `${current.y * 100}%`,
            width: `${current.w * 100}%`,
            height: `${current.h * 100}%`,
          }}
          onPointerDown={startMove}
        >
          <span aria-hidden="true" className="pointer-events-none absolute inset-0">
            <span className="absolute inset-y-0 left-1/3 w-px bg-white/25" />
            <span className="absolute inset-y-0 left-2/3 w-px bg-white/25" />
            <span className="absolute inset-x-0 top-1/3 h-px bg-white/25" />
            <span className="absolute inset-x-0 top-2/3 h-px bg-white/25" />
          </span>
          <button
            type="button"
            aria-label="移动裁切框"
            aria-describedby="crop-help"
            disabled={disabled}
            onPointerDown={startMove}
            onKeyDown={nudge("move")}
            className="absolute left-1/2 top-1/2 grid size-11 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border border-white/25 bg-black/45 text-xs text-white/70 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            <span aria-hidden="true">✥</span>
          </button>
          <button
            type="button"
            aria-label="调整裁切框大小"
            disabled={disabled}
            onPointerDown={startResize}
            onKeyDown={nudge("resize")}
            className="absolute -bottom-2 -right-2 size-6 rounded-sm border-2 border-accent bg-black/70 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <CropNumberField
          label="左侧位置 x"
          value={current.x}
          disabled={disabled}
          onCandidate={(value) => updateField("x", value)}
        />
        <CropNumberField
          label="顶部位置 y"
          value={current.y}
          disabled={disabled}
          onCandidate={(value) => updateField("y", value)}
        />
        <CropNumberField
          label="宽度 w"
          value={current.w}
          disabled={disabled}
          onCandidate={(value) => updateField("w", value)}
        />
        <CropNumberField
          label="高度 h"
          value={current.h}
          disabled={disabled}
          onCandidate={(value) => updateField("h", value)}
        />
      </div>

      <p id="crop-help" className="text-[10px] text-white/35">
        拖动方框移动，拖动右下角调整大小；键盘方向键微调（按住 Shift 步进 0.05），或直接输入数值。
      </p>

      {error && (
        <p role="alert" className="text-[11px] text-red-200/90">
          {error}
        </p>
      )}

      <div className="flex flex-wrap items-center justify-end gap-2">
        <button
          type="button"
          onClick={() => {
            setError(null);
            onChange(null);
          }}
          disabled={disabled}
          className="min-h-11 rounded-lg border border-white/12 px-3 text-xs text-white/55 transition-colors hover:bg-white/[0.05] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40"
        >
          全图
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={disabled}
          className="min-h-11 rounded-lg border border-white/12 px-3 text-xs text-white/65 transition-colors hover:bg-white/[0.05] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40"
        >
          取消
        </button>
        <button
          type="button"
          onClick={onApply}
          disabled={disabled || error !== null}
          className="min-h-11 rounded-lg bg-accent px-4 text-xs font-semibold text-[#101208] transition-colors hover:bg-accent/85 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40"
        >
          应用裁切
        </button>
      </div>
    </section>
  );
}
