"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import type {
  KeyboardEvent as ReactKeyboardEvent,
  MouseEvent as ReactMouseEvent,
  PointerEvent as ReactPointerEvent,
} from "react";

import { CURVE_MAX_POINTS, normalizeCurveSet, roundTo6 } from "@/lib/recipe";
import {
  deleteCurvePoint,
  insertCurvePoint,
  moveCurvePoint,
  sampleCurve,
} from "@/lib/curve";
import { KEYBOARD_COMMIT_DEBOUNCE_MS } from "@/features/editor/components/slider-field";
import type { CurvePoint, CurveSet } from "@/types/session";

const CHANNELS = [
  { id: "master", label: "主曲线", color: "#d8ff5f" },
  { id: "red", label: "红", color: "#ff7b7b" },
  { id: "green", label: "绿", color: "#6ee7a8" },
  { id: "blue", label: "蓝", color: "#7fb0ff" },
] as const satisfies readonly { id: keyof CurveSet; label: string; color: string }[];

const PAD = 4;
const PLOT = 100 - PAD * 2;
const KEYBOARD_STEP = 0.01;
const KEYBOARD_STEP_LARGE = 0.05;
const GRID = [0.25, 0.5, 0.75];

export type CurveChannel = keyof CurveSet;

export interface CurveEditorProps {
  curve: CurveSet;
  disabled?: boolean;
  onChange: (curve: CurveSet) => void;
  onCommit: () => void;
}

function clampUnit(value: number): number {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.min(1, Math.max(0, value));
}

function plotX(value: number): number {
  return PAD + value * PLOT;
}

function plotY(value: number): number {
  return PAD + (1 - value) * PLOT;
}

function pathFor(points: readonly CurvePoint[]): string {
  return sampleCurve(points, 65)
    .map((sample, index) => {
      const command = index === 0 ? "M" : "L";
      return `${command}${plotX(sample.x).toFixed(2)} ${plotY(sample.y).toFixed(2)}`;
    })
    .join(" ");
}

function pointsEqual(left: readonly CurvePoint[], right: readonly CurvePoint[]): boolean {
  return (
    left.length === right.length &&
    left.every((point, index) => point.x === right[index].x && point.y === right[index].y)
  );
}

export function CurveEditor({
  curve,
  disabled = false,
  onChange,
  onCommit,
}: CurveEditorProps) {
  const headingId = useId();
  const hintId = useId();
  const svgRef = useRef<SVGSVGElement>(null);
  const dragRef = useRef<{ index: number; moved: boolean } | null>(null);
  const commitTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [activeChannel, setActiveChannel] = useState<CurveChannel>("master");
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);

  const clearCommitTimer = useCallback(() => {
    if (commitTimerRef.current !== null) {
      clearTimeout(commitTimerRef.current);
      commitTimerRef.current = null;
    }
  }, []);

  useEffect(() => clearCommitTimer, [clearCommitTimer]);

  const points = curve[activeChannel] ?? [];
  const editablePoints = points.length >= 2 ? points : [];
  const activeOption = CHANNELS.find((option) => option.id === activeChannel) ?? CHANNELS[0];
  const selected =
    selectedIndex !== null && selectedIndex < editablePoints.length
      ? editablePoints[selectedIndex]
      : undefined;
  const canDelete =
    selectedIndex !== null && selectedIndex > 0 && selectedIndex < editablePoints.length - 1;
  const allEmpty = CHANNELS.every((option) => (curve[option.id] ?? []).length === 0);

  const applyPoints = (next: readonly CurvePoint[]) => {
    onChange(normalizeCurveSet({ ...curve, [activeChannel]: [...next] }));
  };

  const pointFromClient = useCallback((clientX: number, clientY: number) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect || rect.width <= 0 || rect.height <= 0) {
      return { x: 0, y: 0 };
    }
    const x = ((clientX - rect.left) / rect.width) * 100;
    const y = ((clientY - rect.top) / rect.height) * 100;
    return {
      x: clampUnit((x - PAD) / PLOT),
      y: clampUnit(1 - (y - PAD) / PLOT),
    };
  }, []);

  const scheduleCommit = () => {
    clearCommitTimer();
    commitTimerRef.current = setTimeout(() => {
      commitTimerRef.current = null;
      onCommit();
    }, KEYBOARD_COMMIT_DEBOUNCE_MS);
  };

  const selectChannel = (channel: CurveChannel) => {
    clearCommitTimer();
    setActiveChannel(channel);
    setSelectedIndex(null);
  };

  const handleSurfaceClick = (event: ReactMouseEvent<SVGRectElement>) => {
    if (disabled) {
      return;
    }
    const position = pointFromClient(event.clientX, event.clientY);
    const next = insertCurvePoint(editablePoints, position.x, position.y);
    if (next.length === editablePoints.length) {
      return;
    }
    const insertedX = roundTo6(clampUnit(position.x));
    const index = next.findIndex((point) => Math.abs(point.x - insertedX) < 1e-9);
    setSelectedIndex(index >= 0 ? index : null);
    applyPoints(next);
    onCommit();
  };

  const handleNodePointerDown = (
    event: ReactPointerEvent<SVGCircleElement>,
    index: number,
  ) => {
    if (disabled) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setSelectedIndex(index);
    dragRef.current = { index, moved: false };
  };

  const handleSvgPointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    const drag = dragRef.current;
    if (!drag || disabled) {
      return;
    }
    const position = pointFromClient(event.clientX, event.clientY);
    const next = moveCurvePoint(editablePoints, drag.index, position.x, position.y);
    if (pointsEqual(next, editablePoints)) {
      return;
    }
    drag.moved = true;
    applyPoints(next);
  };

  const handleSvgPointerUp = () => {
    const drag = dragRef.current;
    if (!drag) {
      return;
    }
    dragRef.current = null;
    if (drag.moved) {
      onCommit();
    }
  };

  const handleNodeKeyDown = (
    event: ReactKeyboardEvent<SVGCircleElement>,
    index: number,
  ) => {
    if (disabled) {
      return;
    }
    const current = editablePoints[index];
    if (!current) {
      return;
    }

    if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      const next = deleteCurvePoint(editablePoints, index);
      if (next.length !== editablePoints.length) {
        setSelectedIndex(null);
        applyPoints(next);
        clearCommitTimer();
        onCommit();
      }
      return;
    }

    const step = event.shiftKey ? KEYBOARD_STEP_LARGE : KEYBOARD_STEP;
    let dx = 0;
    let dy = 0;
    switch (event.key) {
      case "ArrowLeft":
        dx = -step;
        break;
      case "ArrowRight":
        dx = step;
        break;
      case "ArrowUp":
        dy = step;
        break;
      case "ArrowDown":
        dy = -step;
        break;
      default:
        return;
    }

    event.preventDefault();
    const next = moveCurvePoint(editablePoints, index, current.x + dx, current.y + dy);
    applyPoints(next);
    scheduleCommit();
  };

  const handleResetChannel = () => {
    clearCommitTimer();
    setSelectedIndex(null);
    applyPoints([]);
    onCommit();
  };

  const handleResetAll = () => {
    clearCommitTimer();
    setSelectedIndex(null);
    onChange(normalizeCurveSet({}));
    onCommit();
  };

  return (
    <section
      aria-labelledby={headingId}
      className="grid gap-3 rounded-xl border border-white/8 bg-white/[0.015] p-4"
    >
      <div className="flex items-center justify-between gap-2">
        <h4 id={headingId} className="text-xs font-medium text-white/80">
          曲线
        </h4>
        <span className="font-mono text-[9px] uppercase tracking-[0.12em] text-white/30">
          Master · RGB
        </span>
      </div>

      <div role="group" aria-label="曲线通道" className="grid grid-cols-4 gap-1">
        {CHANNELS.map((option) => {
          const active = option.id === activeChannel;
          const edited = (curve[option.id] ?? []).length > 0;
          return (
            <button
              key={option.id}
              type="button"
              aria-pressed={active}
              disabled={disabled}
              onClick={() => selectChannel(option.id)}
              className={`min-h-9 rounded-md border px-1 text-[11px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40 ${
                active
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

      <svg
        ref={svgRef}
        data-testid="curve-svg"
        viewBox="0 0 100 100"
        role="group"
        aria-label="曲线编辑区"
        aria-describedby={hintId}
        className={`aspect-square w-full touch-none select-none overflow-visible rounded-lg border border-white/8 bg-black/35 ${
          disabled ? "opacity-50" : ""
        }`}
        onPointerMove={handleSvgPointerMove}
        onPointerUp={handleSvgPointerUp}
        onPointerCancel={handleSvgPointerUp}
      >
        <rect
          data-testid="curve-surface"
          x={0}
          y={0}
          width={100}
          height={100}
          fill="transparent"
          onClick={handleSurfaceClick}
          className={disabled ? undefined : "cursor-crosshair"}
        />
        {GRID.map((value) => (
          <g key={value} className="pointer-events-none">
            <line
              x1={plotX(value)}
              y1={PAD}
              x2={plotX(value)}
              y2={100 - PAD}
              stroke="rgba(255,255,255,0.07)"
              strokeWidth={0.4}
            />
            <line
              x1={PAD}
              y1={plotY(value)}
              x2={100 - PAD}
              y2={plotY(value)}
              stroke="rgba(255,255,255,0.07)"
              strokeWidth={0.4}
            />
          </g>
        ))}
        <line
          x1={plotX(0)}
          y1={plotY(0)}
          x2={plotX(1)}
          y2={plotY(1)}
          stroke="rgba(255,255,255,0.18)"
          strokeWidth={0.4}
          strokeDasharray="2 2"
          className="pointer-events-none"
        />
        <path
          data-testid="curve-line"
          d={pathFor(editablePoints)}
          fill="none"
          stroke={activeOption.color}
          strokeWidth={1.3}
          strokeLinecap="round"
          className="pointer-events-none"
        />
        {editablePoints.map((point, index) => (
          <circle
            key={`${activeChannel}-${index}`}
            data-testid={`curve-node-${index}`}
            role="button"
            tabIndex={disabled ? -1 : 0}
            aria-label={`${activeOption.label}节点 ${index + 1}：输入 ${Math.round(
              point.x * 100,
            )}%，输出 ${Math.round(point.y * 100)}%`}
            cx={plotX(point.x)}
            cy={plotY(point.y)}
            r={selectedIndex === index ? 2.8 : 2.1}
            fill={activeOption.color}
            stroke={selectedIndex === index ? "#ffffff" : "rgba(0,0,0,0.55)"}
            strokeWidth={0.6}
            className={disabled ? undefined : "cursor-grab focus-visible:outline-none"}
            onFocus={() => setSelectedIndex(index)}
            onPointerDown={(event) => handleNodePointerDown(event, index)}
            onKeyDown={(event) => handleNodeKeyDown(event, index)}
          />
        ))}
      </svg>

      <div className="flex items-center justify-between gap-2 font-mono text-[10px] text-white/40">
        <span>
          {selected
            ? `输入 ${Math.round(selected.x * 100)}% · 输出 ${Math.round(selected.y * 100)}%`
            : "点击添加节点 · 拖动调整"}
        </span>
        <span>
          {editablePoints.length}/{CURVE_MAX_POINTS}
        </span>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={disabled || !canDelete}
          onClick={() => {
            if (selectedIndex === null) {
              return;
            }
            const next = deleteCurvePoint(editablePoints, selectedIndex);
            if (next.length === editablePoints.length) {
              return;
            }
            setSelectedIndex(null);
            applyPoints(next);
            onCommit();
          }}
          className="min-h-9 rounded-lg border border-white/12 px-2.5 text-[11px] text-white/60 transition-colors hover:bg-white/[0.06] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-35"
        >
          删除节点
        </button>
        <button
          type="button"
          disabled={disabled || editablePoints.length === 0}
          onClick={handleResetChannel}
          className="min-h-9 rounded-lg border border-white/12 px-2.5 text-[11px] text-white/60 transition-colors hover:bg-white/[0.06] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-35"
        >
          重置通道
        </button>
        <button
          type="button"
          disabled={disabled || allEmpty}
          onClick={handleResetAll}
          className="min-h-9 rounded-lg border border-white/12 px-2.5 text-[11px] text-white/60 transition-colors hover:bg-white/[0.06] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-35"
        >
          重置全部
        </button>
      </div>

      <p id={hintId} className="text-[10px] leading-relaxed text-white/30">
        方向键微调 1%，按住 Shift 为 5%；首尾端点只可上下移动。空曲线保持原图不变。
      </p>
    </section>
  );
}
