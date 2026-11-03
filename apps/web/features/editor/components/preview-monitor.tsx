"use client";

import { createPortal } from "react-dom";

import type { PreviewState } from "@/features/editor/state/editor-reducer";

import { PreviewImage } from "./preview-image";

export interface PreviewMonitorProps {
  preview: PreviewState;
  visible: boolean;
  onReturn: () => void;
}

export function PreviewMonitor({
  preview,
  visible,
  onReturn,
}: PreviewMonitorProps) {
  if (!visible || preview.url === null || typeof document === "undefined") {
    return null;
  }

  return createPortal(
    <aside
      className="preview-monitor"
      aria-label="悬浮预览"
      data-testid="preview-monitor"
    >
      <div className="relative h-full overflow-hidden rounded-2xl border border-white/12 bg-[#0c0d0f]/95 shadow-[0_18px_50px_-20px_rgba(0,0,0,0.95)] backdrop-blur-xl">
        <button
          type="button"
          onClick={onReturn}
          aria-label="返回编辑预览"
          className="relative flex h-full w-full items-center justify-center rounded-2xl p-2 text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          <PreviewImage
            preview={preview}
            alt=""
            showPlaceholder={false}
            className="relative h-full w-full"
            imageClassName="h-full w-full object-contain"
          />
          <span className="pointer-events-none absolute bottom-2 left-1/2 -translate-x-1/2 rounded-full border border-white/12 bg-black/65 px-2.5 py-1 text-[10px] text-white/70">
            返回编辑预览
          </span>
        </button>
      </div>
    </aside>,
    document.body,
  );
}
