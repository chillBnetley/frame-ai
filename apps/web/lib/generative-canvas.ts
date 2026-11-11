import type { GenerativeOutpaintAlignment } from "@/types/generative";

export interface OutpaintMargins {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

export interface OutpaintGeometryRequest {
  baseWidth: number;
  baseHeight: number;
  margins: OutpaintMargins;
  aspectRatio: string | null;
  alignment: GenerativeOutpaintAlignment;
}

export interface OutpaintGeometry extends OutpaintMargins {
  targetWidth: number;
  targetHeight: number;
  isExpanded: boolean;
}

export interface CanvasView {
  scale: number;
  offsetX: number;
  offsetY: number;
}

export const MIN_CANVAS_SCALE = 0.2;
export const MAX_CANVAS_SCALE = 8;
export const CANVAS_ZOOM_STEP = 1.25;

export function parseAspectRatio(ratio: string | null): { width: number; height: number } | null {
  if (!ratio) {
    return null;
  }
  const parts = ratio.split(":");
  const width = Number.parseFloat(parts[0] ?? "");
  const height = Number.parseFloat(parts[1] ?? "");
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    return null;
  }
  return { width, height };
}

/**
 * Resolves the requested outpaint margins into a concrete target canvas. Ratio
 * presets expand the current frame and then distribute the extra pixels
 * according to the alignment, mirroring the server-side composition.
 */
export function computeOutpaintGeometry(
  request: OutpaintGeometryRequest,
): OutpaintGeometry {
  const { baseWidth, baseHeight, aspectRatio, alignment } = request;
  let { top, bottom, left, right } = request.margins;

  const ratio = parseAspectRatio(aspectRatio);
  if (ratio) {
    const currentWidth = baseWidth + left + right;
    const currentHeight = baseHeight + top + bottom;

    let targetWidth: number;
    let targetHeight: number;

    if (ratio.width * currentHeight >= ratio.height * currentWidth) {
      targetHeight = currentHeight;
      targetWidth = Math.ceil((currentHeight * ratio.width) / ratio.height);
    } else {
      targetWidth = currentWidth;
      targetHeight = Math.ceil((currentWidth * ratio.height) / ratio.width);
    }

    const extraWidth = targetWidth - currentWidth;
    const extraHeight = targetHeight - currentHeight;

    if (alignment === "left") {
      right += extraWidth;
    } else if (alignment === "right") {
      left += extraWidth;
    } else {
      const leftHalf = Math.floor(extraWidth / 2);
      left += leftHalf;
      right += extraWidth - leftHalf;
    }

    if (alignment === "top") {
      bottom += extraHeight;
    } else if (alignment === "bottom") {
      top += extraHeight;
    } else {
      const topHalf = Math.floor(extraHeight / 2);
      top += topHalf;
      bottom += extraHeight - topHalf;
    }
  }

  const targetWidth = baseWidth + left + right;
  const targetHeight = baseHeight + top + bottom;

  return {
    top,
    bottom,
    left,
    right,
    targetWidth,
    targetHeight,
    isExpanded: targetWidth > baseWidth || targetHeight > baseHeight,
  };
}

export function clampScale(scale: number): number {
  if (!Number.isFinite(scale)) {
    return 1;
  }
  return Math.min(MAX_CANVAS_SCALE, Math.max(MIN_CANVAS_SCALE, scale));
}

export function fitCanvasView(
  boxWidth: number,
  boxHeight: number,
  contentWidth: number,
  contentHeight: number,
  padding = 0,
): CanvasView {
  if (boxWidth <= 0 || boxHeight <= 0 || contentWidth <= 0 || contentHeight <= 0) {
    return { scale: 1, offsetX: 0, offsetY: 0 };
  }
  const availableWidth = Math.max(1, boxWidth - padding * 2);
  const availableHeight = Math.max(1, boxHeight - padding * 2);
  const scale = Math.min(availableWidth / contentWidth, availableHeight / contentHeight);
  return { scale: clampScale(scale), offsetX: 0, offsetY: 0 };
}

/**
 * Scales the view around a pointer expressed in container-centred pixels so the
 * point under the cursor stays put.
 */
export function zoomCanvasView(
  view: CanvasView,
  factor: number,
  pointerX: number,
  pointerY: number,
): CanvasView {
  const nextScale = clampScale(view.scale * factor);
  if (view.scale === 0 || nextScale === view.scale) {
    return view;
  }
  const applied = nextScale / view.scale;
  return {
    scale: nextScale,
    offsetX: applied * view.offsetX + (1 - applied) * pointerX,
    offsetY: applied * view.offsetY + (1 - applied) * pointerY,
  };
}

export function panCanvasView(view: CanvasView, deltaX: number, deltaY: number): CanvasView {
  return { ...view, offsetX: view.offsetX + deltaX, offsetY: view.offsetY + deltaY };
}

/** Position of the source frame inside the expanded frame, in percentages. */
export function outpaintOverlayRect(
  baseWidth: number,
  baseHeight: number,
  geometry: OutpaintGeometry,
): { left: number; top: number; width: number; height: number } {
  const { targetWidth, targetHeight } = geometry;
  if (targetWidth <= 0 || targetHeight <= 0) {
    return { left: 0, top: 0, width: 100, height: 100 };
  }
  return {
    left: (geometry.left / targetWidth) * 100,
    top: (geometry.top / targetHeight) * 100,
    width: (baseWidth / targetWidth) * 100,
    height: (baseHeight / targetHeight) * 100,
  };
}
