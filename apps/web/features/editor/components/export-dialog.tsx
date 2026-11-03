"use client";

import { useEffect, useRef, useState } from "react";

import { DownloadIcon } from "@/components/icons";
import type { ExportState } from "@/features/editor/hooks/use-export";
import { formatBytes } from "@/lib/format";
import type { ExportFormat } from "@/types/session";

function statusText(state: ExportState): string {
  switch (state.status) {
    case "exporting":
      return "正在导出，高清大图可能需要几十秒…";
    case "success": {
      const dimensions =
        state.width !== null && state.height !== null
          ? `${state.width} × ${state.height}`
          : "尺寸未知";
      const size = state.bytes !== null ? formatBytes(state.bytes) : "大小未知";
      return `导出完成：${state.filename ?? "frame"}（${dimensions}，${size}）。`;
    }
    case "error":
      return `导出失败：${state.error?.message ?? "请稍后重试。"}`;
    default:
      return "";
  }
}

export interface ExportDialogProps {
  open: boolean;
  onClose: () => void;
  state: ExportState;
  dirty: boolean;
  disabled?: boolean;
  onExport: (format: ExportFormat, quality: number | null) => void;
}

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function ExportDialog({
  open,
  onClose,
  state,
  dirty,
  disabled = false,
  onExport,
}: ExportDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const [format, setFormat] = useState<ExportFormat>("jpeg");
  const [quality, setQuality] = useState(92);

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
        onClose();
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
  }, [onClose, open]);

  if (!open) {
    return null;
  }

  const exporting = state.status === "exporting";
  const blocked = disabled || dirty || exporting;
  const status = statusText(state);

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4 backdrop-blur-sm">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="export-dialog-title"
        aria-describedby="export-dialog-description"
        className="w-full max-w-md rounded-2xl border border-white/12 bg-[#101113] p-5 shadow-[0_30px_80px_-20px_rgba(0,0,0,0.9)]"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 id="export-dialog-title" className="text-sm font-medium text-white">
              导出图像
            </h2>
            <p id="export-dialog-description" className="mt-1 text-[11px] text-white/40">
              从原图按当前配方重新渲染；导出会移除 EXIF/XMP/IPTC/GPS 并嵌入 sRGB。
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭导出对话框"
            className="grid size-11 place-items-center rounded-lg text-white/45 transition-colors hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            <span aria-hidden="true">✕</span>
          </button>
        </div>

        <fieldset className="mt-4 grid gap-2" disabled={exporting}>
          <legend className="text-xs text-white/55">导出格式</legend>
          <div className="grid grid-cols-2 gap-2">
            {(
              [
                { value: "jpeg", label: "JPEG", hint: "体积小，适合分享" },
                { value: "png", label: "PNG", hint: "无损，透明区域按白底合成" },
              ] as const
            ).map((option) => (
              <label
                key={option.value}
                className={`flex min-h-11 cursor-pointer items-start gap-2 rounded-lg border px-3 py-2.5 text-xs transition-colors ${
                  format === option.value
                    ? "border-accent/45 bg-accent/[0.08] text-white"
                    : "border-white/12 bg-white/[0.02] text-white/65"
                }`}
              >
                <input
                  type="radio"
                  name="export-format"
                  value={option.value}
                  checked={format === option.value}
                  onChange={() => setFormat(option.value)}
                  className="mt-0.5 accent-[#d8ff5f]"
                />
                <span>
                  <span className="block font-medium">{option.label}</span>
                  <span className="mt-0.5 block text-[10px] text-white/35">{option.hint}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        {format === "jpeg" && (
          <div className="mt-3 grid gap-1.5">
            <label htmlFor="export-quality" className="flex items-baseline justify-between text-xs text-white/55">
              <span>JPEG 质量</span>
              <span className="font-mono text-[10px] text-white/35">60–100</span>
            </label>
            <input
              id="export-quality"
              type="number"
              inputMode="numeric"
              aria-label="JPEG 质量"
              min={60}
              max={100}
              step={1}
              value={quality}
              disabled={exporting}
              onChange={(event) => {
                const parsed = Number.parseInt(event.target.value, 10);
                if (Number.isFinite(parsed)) {
                  setQuality(Math.min(100, Math.max(60, parsed)));
                }
              }}
              className="w-24 rounded-md border border-white/12 bg-black/35 px-2 py-1.5 font-mono text-[11px] text-white/80 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40"
            />
          </div>
        )}

        {dirty && (
          <p className="mt-3 rounded-lg border border-amber-300/25 bg-amber-300/10 px-3 py-2 text-[11px] text-amber-100">
            当前有未保存的调整。请先保存修改，再导出对应的终稿。
          </p>
        )}

        <p
          role="status"
          aria-live="polite"
          className={`mt-3 min-h-5 text-[11px] ${
            state.status === "error" ? "text-red-200/90" : "text-white/45"
          }`}
        >
          {status}
        </p>

        {state.status === "success" && (
          <div className="mt-2 rounded-lg border border-accent/20 bg-accent/[0.05] px-3 py-2">
            <p className="text-xs text-white/75">{state.filename}</p>
            <p className="mt-0.5 font-mono text-[10px] text-white/40">
              {state.width} × {state.height}
              {state.bytes !== null ? ` · ${formatBytes(state.bytes)}` : ""}
            </p>
          </div>
        )}

        {state.status === "success" && state.warnings.includes("denoise_simplified") && (
          <p className="mt-2 rounded-lg border border-amber-300/25 bg-amber-300/10 px-3 py-2 text-[11px] text-amber-100">
            大图降噪使用了简化算法。
          </p>
        )}

        <div className="mt-4 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="min-h-11 rounded-lg border border-white/12 px-3 text-xs text-white/60 transition-colors hover:bg-white/[0.05] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            关闭
          </button>
          <button
            type="button"
            data-autofocus
            disabled={blocked}
            onClick={() => onExport(format, format === "jpeg" ? quality : null)}
            className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-accent px-4 text-xs font-semibold text-[#101208] transition-colors hover:bg-accent/85 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-40"
          >
            <DownloadIcon className="size-4" />
            {exporting ? "正在导出…" : state.status === "success" ? "再次导出" : "开始导出"}
          </button>
        </div>
      </div>
    </div>
  );
}
