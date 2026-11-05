"use client";

import { useEffect, useRef, useState } from "react";

import { originalImageUrl } from "@/lib/api/client";
import type { AnalysisSubject } from "@/types/analysis";

import { bboxToRect, containRect, type PixelRect } from "../overlay-geometry";
import { subjectTypeLabel } from "../presentation";

export interface SubjectOverlayProps {
  imageId: string;
  imageWidth: number;
  imageHeight: number;
  subjects: readonly AnalysisSubject[];
}

export function SubjectOverlay({
  imageId,
  imageWidth,
  imageHeight,
  subjects,
}: SubjectOverlayProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [displayRect, setDisplayRect] = useState<PixelRect | null>(null);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) {
      return;
    }
    const update = () => {
      setDisplayRect(
        containRect(
          element.clientWidth,
          element.clientHeight,
          imageWidth,
          imageHeight,
        ),
      );
    };
    update();
    if (typeof ResizeObserver === "undefined") {
      globalThis.addEventListener("resize", update);
      return () => globalThis.removeEventListener("resize", update);
    }
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, [imageHeight, imageWidth]);

  return (
    <div
      ref={containerRef}
      className="relative h-48 w-full overflow-hidden rounded-lg border border-white/10 bg-black/30"
    >
      {/* eslint-disable-next-line @next/next/no-img-element -- the original image is served locally by the API */}
      <img
        src={originalImageUrl(imageId)}
        alt="原图主体框叠加预览"
        className="absolute inset-0 size-full object-contain"
      />
      {displayRect &&
        subjects.map((subject) => {
          const box = bboxToRect(subject.bbox, displayRect);
          if (!box) {
            return null;
          }
          return (
            <div
              key={`${subject.id}-${subject.regionId}`}
              aria-hidden="true"
              className="absolute rounded-sm border-2 border-accent bg-accent/10"
              style={{
                left: box.left,
                top: box.top,
                width: box.width,
                height: box.height,
              }}
            >
              <span className="absolute left-0 top-0 max-w-full truncate rounded-br-sm bg-accent px-1 py-0.5 font-mono text-[9px] text-white">
                {subject.regionId} · {subjectTypeLabel(subject.type)}
              </span>
            </div>
          );
        })}
    </div>
  );
}