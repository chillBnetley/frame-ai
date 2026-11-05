import type { AnalysisBBox } from "@/types/analysis";

export interface PixelRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export function containRect(
  containerWidth: number,
  containerHeight: number,
  imageWidth: number,
  imageHeight: number,
): PixelRect | null {
  if (
    !Number.isFinite(containerWidth) ||
    !Number.isFinite(containerHeight) ||
    !Number.isFinite(imageWidth) ||
    !Number.isFinite(imageHeight) ||
    containerWidth <= 0 ||
    containerHeight <= 0 ||
    imageWidth <= 0 ||
    imageHeight <= 0
  ) {
    return null;
  }
  const scale = Math.min(
    containerWidth / imageWidth,
    containerHeight / imageHeight,
  );
  const width = imageWidth * scale;
  const height = imageHeight * scale;
  return {
    left: (containerWidth - width) / 2,
    top: (containerHeight - height) / 2,
    width,
    height,
  };
}

export function clampBBox(bbox: AnalysisBBox): AnalysisBBox | null {
  const x = Math.min(Math.max(bbox.x, 0), 1);
  const y = Math.min(Math.max(bbox.y, 0), 1);
  const width = Math.min(Math.max(bbox.width, 0), 1 - x);
  const height = Math.min(Math.max(bbox.height, 0), 1 - y);
  if (width <= 0 || height <= 0) {
    return null;
  }
  return { x, y, width, height };
}

export function bboxToRect(
  bbox: AnalysisBBox,
  rect: PixelRect,
): PixelRect | null {
  const clamped = clampBBox(bbox);
  if (!clamped) {
    return null;
  }
  return {
    left: rect.left + clamped.x * rect.width,
    top: rect.top + clamped.y * rect.height,
    width: clamped.width * rect.width,
    height: clamped.height * rect.height,
  };
}