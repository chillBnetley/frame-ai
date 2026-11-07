"use client";

import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

export interface DeletePhotoDialogProps {
  open: boolean;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function DeletePhotoDialog({
  open,
  busy,
  error,
  onCancel,
  onConfirm,
}: DeletePhotoDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    const previous =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const node = dialogRef.current;
    node?.querySelector<HTMLElement>("[data-autofocus]")?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        if (!busy) {
          onCancel();
        }
        return;
      }
      if (event.key !== "Tab" || !node) {
        return;
      }
      const focusable = Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (focusable.length === 0) {
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previous?.focus();
    };
  }, [busy, onCancel, open]);

  if (!open) {
    return null;
  }

  return createPortal(
    <div className="fixed inset-0 z-50 grid place-items-center bg-[rgba(241,243,242,0.72)] p-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="delete-photo-title"
        aria-describedby="delete-photo-description"
        className="w-full max-w-md rounded-2xl border border-red-300/25 bg-[#101113] p-5 shadow-[0_30px_80px_-20px_rgba(0,0,0,0.9)]"
      >
        <h2 id="delete-photo-title" className="text-sm font-medium text-white">
          删除这张照片？
        </h2>
        <p
          id="delete-photo-description"
          className="mt-2 text-[11px] leading-relaxed text-white/55"
        >
          原图、编辑会话与历史版本、AI 分析与缓存副本会从本机永久删除，无法恢复。
          如需保留，请先下载原图或导出成片。
        </p>

        {error && (
          <p
            role="alert"
            className="mt-3 rounded-lg border border-red-300/25 bg-red-300/10 px-3 py-2 text-[11px] text-red-100"
          >
            {error}
          </p>
        )}

        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            type="button"
            data-autofocus
            disabled={busy}
            onClick={onCancel}
            className="min-h-11 rounded-lg border border-white/12 px-3 text-xs text-white/60 transition-colors hover:bg-white/[0.05] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40"
          >
            取消
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={onConfirm}
            className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-[#ff8f8f] px-4 text-xs font-semibold text-[#2a0808] transition-colors hover:bg-[#ffa8a8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#ff8f8f] disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? "正在删除…" : "永久删除"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
