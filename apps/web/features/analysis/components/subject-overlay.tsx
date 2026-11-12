"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

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

function useContainRect(
  imageWidth: number,
  imageHeight: number,
  active: boolean,
) {
  const ref = useRef<HTMLDivElement>(null);
  const [rect, setRect] = useState<PixelRect | null>(null);

  useEffect(() => {
    const element = ref.current;
    if (!active || !element) {
      return;
    }
    const update = () => {
      setRect(
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
  }, [active, imageHeight, imageWidth]);

  return [ref, rect] as const;
}

function SubjectBoxes({
  subjects,
  rect,
}: {
  subjects: readonly AnalysisSubject[];
  rect: PixelRect | null;
}) {
  if (!rect) {
    return null;
  }
  return (
    <>
      {subjects.map((subject) => {
        const box = bboxToRect(subject.bbox, rect);
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
    </>
  );
}

export function SubjectOverlay({
  imageId,
  imageWidth,
  imageHeight,
  subjects,
}: SubjectOverlayProps) {
  const [open, setOpen] = useState(false);
  const [inlineRef, inlineRect] = useContainRect(
    imageWidth,
    imageHeight,
    true,
  );
  const [zoomRef, zoomRect] = useContainRect(imageWidth, imageHeight, open);
  const closeRef = useRef<HTMLButtonElement>(null);
  const triggerRef = useRef<HTMLDivElement>(null);

  const close = useCallback(() => {
    setOpen(false);
    triggerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  const lightbox =
    open && typeof document !== "undefined"
      ? createPortal(
          <div
            role="dialog"
            aria-modal="true"
            aria-label="主体框放大预览"
            className="fixed inset-0 z-50 flex flex-col bg-[#0d1412]/92 p-3 sm:p-6"
          >
            <div className="mb-2 flex items-center justify-between gap-3">
              <p className="text-xs text-[#f7faf8]/75">原图主体框 · 放大查看</p>
              <button
                ref={closeRef}
                type="button"
                onClick={close}
                aria-label="关闭主体框放大预览"
                className="grid size-10 place-items-center rounded-lg border border-[rgba(255,255,255,0.3)] text-sm text-[#f7faf8]/85 transition-colors hover:bg-[rgba(255,255,255,0.12)] hover:text-[#f7faf8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                <span aria-hidden="true">✕</span>
              </button>
            </div>
            <div
              ref={zoomRef}
              className="relative min-h-0 flex-1 overflow-hidden rounded-xl border border-[rgba(255,255,255,0.14)] bg-[rgba(0,0,0,0.35)]"
            >
              {/* eslint-disable-next-line @next/next/no-img-element -- the original image is served locally by the API */}
              <img
                src={originalImageUrl(imageId)}
                alt="主体框放大预览图"
                className="absolute inset-0 size-full object-contain"
              />
              <SubjectBoxes subjects={subjects} rect={zoomRect} />
            </div>
            <p className="mt-2 text-[11px] text-[#f7faf8]/55">
              按 Esc 或点击右上角 × 退出预览
            </p>
          </div>,
          document.body,
        )
      : null;

  return (
    <>
      <div
        ref={triggerRef}
        role="button"
        tabIndex={0}
        aria-label="放大查看主体框"
        aria-haspopup="dialog"
        onClick={() => setOpen(true)}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            setOpen(true);
          }
        }}
        className="group relative h-48 w-full cursor-zoom-in overflow-hidden rounded-lg border border-white/10 bg-black/30 transition-colors hover:border-[#c3cec8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- the original image is served locally by the API */}
        <img
          src={originalImageUrl(imageId)}
          alt="原图主体框叠加预览"
          className="absolute inset-0 size-full object-contain"
          draggable={false}
        />
        <div ref={inlineRef} className="absolute inset-0">
          <SubjectBoxes subjects={subjects} rect={inlineRect} />
        </div>
        <span
          aria-hidden="true"
          className="pointer-events-none absolute bottom-1.5 right-1.5 rounded-full border border-[rgba(255,255,255,0.45)] bg-[rgba(0,0,0,0.4)] px-2 py-0.5 text-[10px] text-[#f7faf8] transition-opacity group-hover:opacity-100 sm:opacity-80"
        >
          单击放大
        </span>
      </div>
      {lightbox}
    </>
  );
}
