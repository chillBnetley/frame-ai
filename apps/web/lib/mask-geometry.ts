import type { Crop, UserMask } from "@/types/session";

export interface Size {
  width: number;
  height: number;
}

export interface NormalizedRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface MaskGeometry {
  transform: AffineTransform;
  output: Size;
}

export interface Point {
  x: number;
  y: number;
}

export interface RectBounds {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface AffineTransform {
  a: number;
  b: number;
  c: number;
  d: number;
  e: number;
  f: number;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function roundHalfEven(value: number): number {
  const floor = Math.floor(value);
  const fraction = value - floor;
  if (fraction > 0.5) {
    return floor + 1;
  }
  if (fraction < 0.5) {
    return floor;
  }
  return floor % 2 === 0 ? floor : floor + 1;
}

export function inscribedScale(width: number, height: number, rotationDeg: number): number {
  if (width <= 0 || height <= 0) {
    throw new Error("width and height must be positive");
  }
  const radians = (Math.abs(rotationDeg) * Math.PI) / 180;
  const denominator = Math.cos(radians) + Math.max(width / height, height / width) * Math.sin(radians);
  return 1 / denominator;
}

export function rotationTargetSize(source: Size, rotationDeg: number): Size {
  const scale = inscribedScale(source.width, source.height, rotationDeg);
  return {
    width: Math.max(1, roundHalfEven(source.width * scale)),
    height: Math.max(1, roundHalfEven(source.height * scale)),
  };
}

export function cropBounds(crop: Crop | null | undefined, size: Size): RectBounds {
  if (!crop) {
    return { x0: 0, y0: 0, x1: size.width, y1: size.height };
  }
  const x0 = clamp(roundHalfEven(crop.x * size.width), 0, size.width - 1);
  const y0 = clamp(roundHalfEven(crop.y * size.height), 0, size.height - 1);
  const x1 = clamp(roundHalfEven((crop.x + crop.w) * size.width), x0 + 1, size.width);
  const y1 = clamp(roundHalfEven((crop.y + crop.h) * size.height), y0 + 1, size.height);
  return { x0, y0, x1, y1 };
}

export function rotationMatrix(
  source: Size,
  rotationDeg: number,
  target: Size,
): AffineTransform {
  const centerX = (source.width - 1) / 2;
  const centerY = (source.height - 1) / 2;
  const radians = (-rotationDeg * Math.PI) / 180;
  const alpha = Math.cos(radians);
  const beta = Math.sin(radians);
  return {
    a: alpha,
    b: beta,
    c: (1 - alpha) * centerX - beta * centerY + (target.width - 1) / 2 - centerX,
    d: -beta,
    e: alpha,
    f: beta * centerX + (1 - alpha) * centerY + (target.height - 1) / 2 - centerY,
  };
}

export function sourceToDisplayTransform(
  source: Size,
  rotationDeg: number,
  crop: Crop | null | undefined,
  output: Size,
): AffineTransform {
  const target = rotationTargetSize(source, rotationDeg);
  const bounds = cropBounds(crop, target);
  const matrix = rotationMatrix(source, rotationDeg, target);
  const outputWidth = bounds.x1 - bounds.x0;
  const outputHeight = bounds.y1 - bounds.y0;
  if (outputWidth !== output.width || outputHeight !== output.height) {
    throw new Error("mask geometry does not match the output dimensions");
  }
  return {
    a: (matrix.a * source.width) / outputWidth,
    b: (matrix.b * source.height) / outputWidth,
    c: (matrix.c - bounds.x0) / outputWidth,
    d: (matrix.d * source.width) / outputHeight,
    e: (matrix.e * source.height) / outputHeight,
    f: (matrix.f - bounds.y0) / outputHeight,
  };
}

export function applyTransform(transform: AffineTransform, point: Point): Point {
  return {
    x: transform.a * point.x + transform.b * point.y + transform.c,
    y: transform.d * point.x + transform.e * point.y + transform.f,
  };
}

export function invertTransform(transform: AffineTransform): AffineTransform | null {
  const determinant = transform.a * transform.e - transform.b * transform.d;
  if (Math.abs(determinant) < 1e-12) {
    return null;
  }
  return {
    a: transform.e / determinant,
    b: -transform.b / determinant,
    c: (transform.b * transform.f - transform.c * transform.e) / determinant,
    d: -transform.d / determinant,
    e: transform.a / determinant,
    f: (transform.c * transform.d - transform.a * transform.f) / determinant,
  };
}

export function displayToSourcePoint(
  transform: AffineTransform,
  point: Point,
): Point | null {
  const inverse = invertTransform(transform);
  return inverse ? applyTransform(inverse, point) : null;
}

export function svgMatrix(transform: AffineTransform): string {
  return `matrix(${transform.a} ${transform.d} ${transform.b} ${transform.e} ${transform.c} ${transform.f})`;
}

const SYNTHETIC_SOURCE_HEIGHT = 4096;

export function previewMaskGeometry(
  preview: Size,
  rotationDeg: number,
  crop: Crop | null | undefined,
  source: Size | null | undefined,
): MaskGeometry | null {
  let base: Size;
  if (source && source.width > 0 && source.height > 0) {
    base = source;
  } else if (preview.width > 0 && preview.height > 0) {
    // Restored sessions do not expose the original pixel size. The rotated
    // canvas keeps the source aspect ratio, so the preview and crop recover it.
    const cropWidth = crop?.w ?? 1;
    const cropHeight = crop?.h ?? 1;
    const targetAspect = (preview.width * cropHeight) / (preview.height * cropWidth);
    base = {
      width: Math.max(1, Math.round(SYNTHETIC_SOURCE_HEIGHT * targetAspect)),
      height: SYNTHETIC_SOURCE_HEIGHT,
    };
  } else {
    return null;
  }

  const target = rotationTargetSize(base, rotationDeg);
  const bounds = cropBounds(crop, target);
  const output = {
    width: bounds.x1 - bounds.x0,
    height: bounds.y1 - bounds.y0,
  };
  return {
    transform: sourceToDisplayTransform(base, rotationDeg, crop, output),
    output,
  };
}

export function rectangleOutline(rect: NormalizedRect): Point[] {
  return [
    { x: rect.x, y: rect.y },
    { x: rect.x + rect.width, y: rect.y },
    { x: rect.x + rect.width, y: rect.y + rect.height },
    { x: rect.x, y: rect.y + rect.height },
  ];
}

export function ellipseOutline(rect: NormalizedRect, samples = 64): Point[] {
  const centerX = rect.x + rect.width / 2;
  const centerY = rect.y + rect.height / 2;
  const radiusX = rect.width / 2;
  const radiusY = rect.height / 2;
  const count = Math.max(8, Math.round(samples));
  return Array.from({ length: count }, (_, index) => {
    const angle = (index / count) * Math.PI * 2;
    return {
      x: centerX + radiusX * Math.cos(angle),
      y: centerY + radiusY * Math.sin(angle),
    };
  });
}

function maskShapeOutline(mask: UserMask, samples: number): Point[] {
  return mask.shape === "ellipse" ? ellipseOutline(mask, samples) : rectangleOutline(mask);
}

export function maskOutlinePoints(
  mask: UserMask,
  transform: AffineTransform,
  samples = 64,
): Point[] {
  return maskShapeOutline(mask, samples).map((point) =>
    applyTransform(transform, point),
  );
}

export function maskInnerOutlinePoints(
  mask: UserMask,
  transform: AffineTransform,
  samples = 64,
): Point[] {
  const feather = clamp(mask.feather, 0, 100) / 100;
  if (feather <= 0) {
    return [];
  }
  const inset: NormalizedRect = {
    x: mask.x + (mask.width * feather) / 2,
    y: mask.y + (mask.height * feather) / 2,
    width: mask.width * (1 - feather),
    height: mask.height * (1 - feather),
  };
  const shape: UserMask = { ...mask, ...inset };
  return maskShapeOutline(shape, samples).map((point) =>
    applyTransform(transform, point),
  );
}

function roundTo4(value: number): number {
  return Math.round(value * 10000) / 10000;
}

export function displayRectToSourceRegion(
  transform: AffineTransform,
  start: Point,
  end: Point,
): NormalizedRect | null {
  const corners = [
    { x: start.x, y: start.y },
    { x: end.x, y: start.y },
    { x: end.x, y: end.y },
    { x: start.x, y: end.y },
  ]
    .map((point) => displayToSourcePoint(transform, point))
    .filter((point): point is Point => point !== null);
  if (corners.length !== 4) {
    return null;
  }
  const xs = corners.map((point) => point.x);
  const ys = corners.map((point) => point.y);
  const x = roundTo4(clamp(Math.min(...xs), 0, 0.99));
  const y = roundTo4(clamp(Math.min(...ys), 0, 0.99));
  return {
    x,
    y,
    width: roundTo4(clamp(Math.max(...xs) - x, 0.01, 1 - x)),
    height: roundTo4(clamp(Math.max(...ys) - y, 0.01, 1 - y)),
  };
}

export function outlineOverlapsDisplay(points: readonly Point[]): boolean {
  if (points.length === 0) {
    return false;
  }
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  return Math.max(...xs) > 0 && Math.min(...xs) < 1 && Math.max(...ys) > 0 && Math.min(...ys) < 1;
}
