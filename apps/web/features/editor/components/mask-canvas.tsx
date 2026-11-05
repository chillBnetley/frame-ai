"use client";

import { useId, useMemo, useRef, useState } from "react";
import type {
  PointerEvent as ReactPointerEvent,
} from "react";

import {
  displayRectToSourceRegion,
  maskInnerOutlinePoints,
  maskOutlinePoints,
  previewMaskGeometry,
  type NormalizedRect,
  type Point,
  type Size,
} from "@/lib/mask-geometry";
import type { Crop, UserMask } from "@/types/session";

const DRAG_THRESHOLD_PX = 4;
const VIEWBOX_SIZE = 1000;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function toSvgPoints(points: readonly Point[]): string {
  return points
    .map(
      (point) =>
        `${(point.x * VIEWBOX_SIZE).toFixed(2)},${(point.y * VIEWBOX_SIZE).toFixed(2)}`,
    )
    .join(" ");
}

function pointerPoint(
  event: ReactPointerEvent<HTMLElement>,
  rect: DOMRect,
): Point {
  return {
    x: clamp((event.clientX - rect.left) / rect.width, 0, 1),
    y: clamp((event.clientY - rect.top) / rect.height, 0, 1),
  };
}

interface DragState {
  start: Point;
  moved: boolean;
}

export interface MaskCanvasProps {
  imageUrl: string | null;
  previewWidth: number;
  previewHeight: number;
  rotationDeg: number;
  crop: Crop | null;
  sourceSize: Size | null;
  mask: UserMask;
  disabled?: boolean;
  onChangeRegion: (region: NormalizedRect) => void;
  onCommit: () => void;
}

export function MaskCanvas({
  imageUrl,
  previewWidth,
  previewHeight,
  rotationDeg,
  crop,
  sourceSize,
  mask,
  disabled = false,
  onChangeRegion,
  onCommit,
}: MaskCanvasProps) {
  const hintId = useId();
  const containerRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<DragState | null>(null);
  const [dragging, setDragging] = useState(false);
  const [failedReferenceUrl, setFailedReferenceUrl] = useState<string | null>(null);
  const referenceFailed = failedReferenceUrl !== null && failedReferenceUrl === imageUrl;

  const geometry = useMemo(
    () =>
      previewMaskGeometry(
        { width: previewWidth, height: previewHeight },
        rotationDeg,
        crop,
        sourceSize,
      ),
    [crop, previewHeight, previewWidth, rotationDeg, sourceSize],
  );

  const outline = useMemo(
    () => (geometry ? toSvgPoints(maskOutlinePoints(mask, geometry.transform)) : ""),
    [geometry, mask],
  );
  const innerOutline = useMemo(
    () =>
      geometry
        ? toSvgPoints(maskInnerOutlinePoints(mask, geometry.transform))
        : "",
    [geometry, mask],
  );

  const handlePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (disabled || !geometry) {
      return;
    }
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0 || rect.height === 0) {
      return;
    }
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    dragRef.current = {
      start: pointerPoint(event, rect),
      moved: false,
    };
    setDragging(true);
  };

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    const rect = containerRef.current?.getBoundingClientRect();
    if (!drag || !geometry || !rect || rect.width === 0 || rect.height === 0) {
      return;
    }
    const point = pointerPoint(event, rect);
    if (!drag.moved) {
      const dx = (point.x - drag.start.x) * rect.width;
      const dy = (point.y - drag.start.y) * rect.height;
      if (Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) {
        return;
      }
      drag.moved = true;
    }
    const region = displayRectToSourceRegion(geometry.transform, drag.start, point);
    if (region) {
      onChangeRegion(region);
    }
  };

  const endDrag = () => {
    const drag = dragRef.current;
    dragRef.current = null;
    setDragging(false);
    if (drag?.moved) {
      onCommit();
    }
  };

  if (!geometry) {
    return (
      <p className="rounded-lg border border-white/8 bg-black/25 px-3 py-4 text-[11px] text-white/40">
        等待预览尺寸后即可在画面中框选区域；也可以直接输入数值。
      </p>
    );
  }

  return (
    <div className="grid gap-2">
      <div
        ref={containerRef}
        data-testid="mask-canvas"
        className={`relative overflow-hidden rounded-lg bg-black ring-1 ring-white/10 ${
          disabled ? "" : "cursor-crosshair touch-none"
        }`}
        style={{ aspectRatio: `${geometry.output.width} / ${geometry.output.height}` }}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        {imageUrl && !referenceFailed ? (
          // eslint-disable-next-line @next/next/no-img-element -- previews are content-addressed JPEGs served by the API
          <img
            src={imageUrl}
            alt="局部蒙版预览"
            className="absolute inset-0 h-full w-full object-fill"
            draggable={false}
            onError={() => setFailedReferenceUrl(imageUrl)}
          />
        ) : (
          <p className="absolute inset-0 grid place-items-center px-4 text-center text-[11px] text-white/40">
            {referenceFailed
              ? "参考图已过期，任何新的调整都会重新生成参考图；框选区域不受影响。"
              : "正在生成预览…"}
          </p>
        )}
        <svg
          aria-hidden="true"
          viewBox={`0 0 ${VIEWBOX_SIZE} ${VIEWBOX_SIZE}`}
          preserveAspectRatio="none"
          className="pointer-events-none absolute inset-0 h-full w-full"
        >
          <polygon
            data-testid="mask-outline"
            points={outline}
            fill="rgba(216, 255, 95, 0.16)"
            fillOpacity={clamp(mask.opacity / 100, 0, 1)}
            stroke="#d8ff5f"
            strokeWidth={1.5}
            vectorEffect="non-scaling-stroke"
          />
          {innerOutline && (
            <polygon
              data-testid="mask-inner-outline"
              points={innerOutline}
              fill="none"
              stroke="#d8ff5f"
              strokeOpacity={0.7}
              strokeDasharray="12 8"
              strokeWidth={1}
              vectorEffect="non-scaling-stroke"
            />
          )}
        </svg>
        {dragging && (
          <span className="pointer-events-none absolute bottom-2 left-2 rounded-md bg-black/70 px-2 py-1 text-[10px] text-white/80">
            松开以应用框选区域
          </span>
        )}
      </div>
      <p id={hintId} className="text-[10px] leading-relaxed text-white/30">
        在预览上拖动可重新框选区域；框选结果会按原图坐标保存，旋转或裁切后仍跟随内容。也可以直接输入数值精确调整。
      </p>
    </div>
  );
}
