"use client";

import { useEffect, useRef } from "react";

import { generativeResultImageUrl } from "@/lib/api/generative";
import {
  CANVAS_ZOOM_STEP,
  outpaintOverlayRect,
  type CanvasView,
  type OutpaintGeometry,
} from "@/lib/generative-canvas";
import type { GenerativeResultView } from "@/types/generative";
import { PAN_STEP_PX, type StudioBaseLayer, type StudioCompareMode } from "./use-studio-state";

export interface StudioCanvasProps {
  baseImageUrl: string | null;
  originalImageUrl: string | null;
  result: GenerativeResultView | null;
  baseLayer: StudioBaseLayer;
  resultVisible: boolean;
  maskOverlayVisible: boolean;
  maskImageUrl: string | null;
  outpaintGeometry: OutpaintGeometry | null;
  baseWidth: number;
  baseHeight: number;
  view: CanvasView;
  compare: StudioCompareMode;
  comparePosition: number;
  isRunning: boolean;
  stageLabel: string | null;
  onZoom: (factor: number, pointerX: number, pointerY: number) => void;
  onPan: (deltaX: number, deltaY: number) => void;
  onFit: (boxWidth: number, boxHeight: number, contentWidth: number, contentHeight: number) => void;
  onComparePositionChange: (position: number) => void;
  onViewportSize?: (width: number, height: number) => void;
}

const WHEEL_ZOOM_FACTOR_BASE = 1.0018;
const PAN_KEYS: Record<string, [number, number]> = {
  ArrowUp: [0, PAN_STEP_PX],
  ArrowDown: [0, -PAN_STEP_PX],
  ArrowLeft: [PAN_STEP_PX, 0],
  ArrowRight: [-PAN_STEP_PX, 0],
};

export function StudioCanvas({
  baseImageUrl,
  originalImageUrl,
  result,
  baseLayer,
  resultVisible,
  maskOverlayVisible,
  maskImageUrl,
  outpaintGeometry,
  baseWidth,
  baseHeight,
  view,
  compare,
  comparePosition,
  isRunning,
  stageLabel,
  onZoom,
  onPan,
  onFit,
  onComparePositionChange,
  onViewportSize,
}: StudioCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{ x: number; y: number } | null>(null);
  const autoFitRef = useRef(false);

  const expanded = outpaintGeometry !== null && outpaintGeometry.isExpanded;
  const frameWidth = expanded ? outpaintGeometry.targetWidth : baseWidth;
  const frameHeight = expanded ? outpaintGeometry.targetHeight : baseHeight;
  const sourceRect = expanded
    ? outpaintOverlayRect(baseWidth, baseHeight, outpaintGeometry)
    : { left: 0, top: 0, width: 100, height: 100 };

  // Keep the latest callbacks reachable from the listeners bound once on mount.
  const handlersRef = useRef({ onZoom, onPan, onFit, onViewportSize });
  useEffect(() => {
    handlersRef.current = { onZoom, onPan, onFit, onViewportSize };
  });

  useEffect(() => {
    const node = containerRef.current;
    if (node === null) {
      return;
    }

    const wheelHandler = (event: WheelEvent) => {
      event.preventDefault();
      const rect = node.getBoundingClientRect();
      const factor = Math.pow(WHEEL_ZOOM_FACTOR_BASE, -event.deltaY);
      handlersRef.current.onZoom(
        factor,
        event.clientX - rect.left - rect.width / 2,
        event.clientY - rect.top - rect.height / 2,
      );
    };
    node.addEventListener("wheel", wheelHandler, { passive: false });

    let observer: ResizeObserver | null = null;
    if (typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver((entries) => {
        const entry = entries[0];
        if (!entry) {
          return;
        }
        const width = entry.contentRect.width;
        const height = entry.contentRect.height;
        if (width <= 0 || height <= 0) {
          return;
        }
        handlersRef.current.onViewportSize?.(width, height);
        if (!autoFitRef.current) {
          autoFitRef.current = true;
          handlersRef.current.onFit(width, height, frameWidth, frameHeight);
        }
      });
      observer.observe(node);
    }

    return () => {
      node.removeEventListener("wheel", wheelHandler);
      observer?.disconnect();
    };
  }, [frameWidth, frameHeight]);

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>): void => {
    if (event.button !== 0) {
      return;
    }
    dragRef.current = { x: event.clientX, y: event.clientY };
    // The pointer capture is released implicitly on pointerup, so no release call here.
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>): void => {
    const last = dragRef.current;
    if (last === null) {
      return;
    }
    const deltaX = event.clientX - last.x;
    const deltaY = event.clientY - last.y;
    dragRef.current = { x: event.clientX, y: event.clientY };
    if (deltaX !== 0 || deltaY !== 0) {
      onPan(deltaX, deltaY);
    }
  };

  const endDrag = (): void => {
    dragRef.current = null;
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>): void => {
    const pan = PAN_KEYS[event.key];
    if (pan) {
      event.preventDefault();
      onPan(pan[0], pan[1]);
      return;
    }
    if (event.key === "+" || event.key === "=") {
      event.preventDefault();
      onZoom(CANVAS_ZOOM_STEP, 0, 0);
      return;
    }
    if (event.key === "-" || event.key === "_") {
      event.preventDefault();
      onZoom(1 / CANVAS_ZOOM_STEP, 0, 0);
    }
  };

  const showResult = result !== null && (resultVisible || compare !== "off");
  const boxWidth = Math.max(1, Math.round(frameWidth * view.scale));
  const boxHeight = Math.max(1, Math.round(frameHeight * view.scale));
  const bottomUrl = baseLayer === "original" ? originalImageUrl : baseImageUrl;
  const bottomLabel = baseLayer === "original" ? "原始照片" : "当前版本";
  const resultUrl = result ? generativeResultImageUrl(result.resultId) : null;

  const frameStyle = (width: number, height: number): React.CSSProperties => ({
    width,
    height,
    transform: `translate(${view.offsetX}px, ${view.offsetY}px)`,
  });

  if (compare === "side" && result && resultUrl) {
    return (
      <div
        ref={containerRef}
        tabIndex={0}
        role="group"
        aria-label="生成结果并排对比"
        onKeyDown={handleKeyDown}
        className="studio-canvas flex h-full min-h-64 w-full items-center justify-center gap-3 overflow-hidden rounded-xl border border-[#e4e8e5] bg-[#eceeec] p-3 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#277a68]"
      >
        {[
          { url: bottomUrl, label: `修改前 · ${bottomLabel}` },
          { url: resultUrl, label: "AI 结果" },
        ].map((pane) => (
          <figure key={pane.label} className="relative flex h-full min-w-0 flex-1 flex-col">
            <figcaption className="mb-1.5 text-[11px] text-[#69716c]">{pane.label}</figcaption>
            {pane.url ? (
              // eslint-disable-next-line @next/next/no-img-element -- object URLs are not next/image targets
              <img
                src={pane.url}
                alt={pane.label}
                className="min-h-0 w-full flex-1 object-contain"
                draggable={false}
              />
            ) : (
              <div className="flex min-h-0 flex-1 items-center justify-center text-xs text-[#8a938e]">
                等待图片…
              </div>
            )}
          </figure>
        ))}
      </div>
    );
  }

  const sliderClip =
    compare === "slider" ? { clipPath: `inset(0 0 0 ${comparePosition}%)` } : undefined;

  return (
    <div
      ref={containerRef}
      tabIndex={0}
      role="group"
      aria-label="生成画布，可拖动平移、滚轮缩放"
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onKeyDown={handleKeyDown}
      className="studio-canvas relative flex h-full min-h-64 w-full cursor-grab touch-none items-center justify-center overflow-hidden rounded-xl border border-[#e4e8e5] bg-[#eceeec] active:cursor-grabbing focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#277a68]"
    >
      <div className="relative shrink-0" style={frameStyle(boxWidth, boxHeight)}>
        {expanded && (
          <div
            aria-hidden="true"
            className="absolute inset-0 rounded-sm border border-dashed border-[#277a68]/70 bg-[#277a68]/[0.06]"
          />
        )}

        {bottomUrl && (
          // eslint-disable-next-line @next/next/no-img-element -- object URLs are not next/image targets
          <img
            src={bottomUrl}
            alt={bottomLabel}
            draggable={false}
            className="absolute select-none"
            style={{
              left: `${sourceRect.left}%`,
              top: `${sourceRect.top}%`,
              width: `${sourceRect.width}%`,
              height: `${sourceRect.height}%`,
            }}
          />
        )}

        {showResult && resultUrl && (
          // eslint-disable-next-line @next/next/no-img-element -- object URLs are not next/image targets
          <img
            src={resultUrl}
            alt="AI 生成结果"
            draggable={false}
            className="absolute inset-0 select-none"
            style={sliderClip}
          />
        )}

        {maskOverlayVisible && maskImageUrl && !showResult && (
          // eslint-disable-next-line @next/next/no-img-element -- object URLs are not next/image targets
          <img
            src={maskImageUrl}
            alt=""
            aria-hidden="true"
            draggable={false}
            className="pointer-events-none absolute select-none opacity-40 mix-blend-multiply invert"
            style={{
              left: `${sourceRect.left}%`,
              top: `${sourceRect.top}%`,
              width: `${sourceRect.width}%`,
              height: `${sourceRect.height}%`,
            }}
          />
        )}
      </div>

      {!bottomUrl && (
        <p className="absolute text-xs text-[#8a938e]">等待渲染预览…</p>
      )}

      <div className="pointer-events-none absolute left-3 top-3 flex flex-col items-start gap-1.5">
        <span className="rounded-full border border-[#d7dcd8] bg-[rgba(255,255,255,0.92)] px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.12em] text-[#3d4541]">
          {showResult ? "AI 结果" : `底图 · ${bottomLabel}`}
        </span>
        {isRunning && stageLabel && (
          <span className="rounded-full border border-[#277a68]/40 bg-[#e7f1ed] px-2.5 py-1 text-[10px] text-[#1f6252]">
            {stageLabel}
          </span>
        )}
        {expanded && !showResult && (
          <span className="rounded-full border border-[#d7dcd8] bg-[rgba(255,255,255,0.92)] px-2.5 py-1 text-[10px] text-[#69716c]">
            虚线为扩充目标画幅 {frameWidth} × {frameHeight}
          </span>
        )}
      </div>

      {compare === "slider" && (
        <div className="absolute inset-x-0 bottom-0 flex items-center gap-3 border-t border-[#e4e8e5] bg-[rgba(255,255,255,0.94)] px-3 py-2">
          <label htmlFor="studio-compare-position" className="text-[11px] text-[#69716c]">
            对比位置
          </label>
          <input
            id="studio-compare-position"
            type="range"
            min={0}
            max={100}
            step={1}
            value={comparePosition}
            onChange={(event) => onComparePositionChange(Number(event.target.value))}
            className="h-1.5 w-full accent-[#277a68]"
          />
          <span className="w-10 text-right font-mono text-[11px] text-[#3d4541]">
            {comparePosition}%
          </span>
        </div>
      )}
    </div>
  );
}
