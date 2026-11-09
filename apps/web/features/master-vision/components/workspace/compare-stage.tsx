"use client";

import { useEffect, useState } from "react";

type ViewMode = "split" | "original" | "result";

export function MasterVisionCompare({
  originalUrl,
  resultUrl,
  loading,
  error,
  hint,
  onRetry,
  onImageError,
}: {
  originalUrl: string | null;
  resultUrl: string | null;
  loading: boolean;
  error: string | null;
  hint?: string;
  onRetry?: () => void;
  onImageError?: () => void;
}) {
  const [view, setView] = useState<ViewMode>("split");
  const [split, setSplit] = useState(50);
  const [zoomed, setZoomed] = useState(false);
  const [zoom, setZoom] = useState(1.6);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") setZoomed(false);
    };
    if (zoomed) {
      document.addEventListener("keydown", handler);
    }
    return () => document.removeEventListener("keydown", handler);
  }, [zoomed]);

  const hasResult = resultUrl !== null;
  const activeView = hasResult ? view : "original";

  return (
    <section aria-labelledby="compare-heading" className="flex min-h-0 flex-col gap-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id="compare-heading" className="text-sm font-semibold text-[#2c3a34]">
            成片预览
          </h2>
          <p className="mt-0.5 text-[11px] text-[#8a9690]">
            {hint ?? "预览来自阶段四真实渲染；拖动分割线查看原图与处理结果。"}
          </p>
        </div>
        <div className="flex flex-wrap gap-1" role="group" aria-label="预览模式">
          {(
            [
              ["split", "左右对比"],
              ["original", "查看原图"],
              ["result", "查看结果"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              disabled={value === "result" && !hasResult}
              aria-pressed={activeView === value}
              onClick={() => setView(value)}
              className="min-h-9 rounded-lg border border-[#dfe5e1] bg-white px-3 text-[11px] text-[#5f6d66] transition-colors hover:bg-[#f5f8f6] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent aria-pressed:border-[#9dbdaf] aria-pressed:bg-[#eaf3ef] aria-pressed:text-[#1f6a5a] disabled:opacity-40"
            >
              {label}
            </button>
          ))}
          <button
            type="button"
            disabled={!hasResult}
            onClick={() => setZoomed(true)}
            className="min-h-9 rounded-lg border border-[#dfe5e1] bg-white px-3 text-[11px] text-[#5f6d66] transition-colors hover:bg-[#f5f8f6] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40"
          >
            放大查看
          </button>
        </div>
      </div>

      <div className="relative min-h-[320px] overflow-hidden rounded-2xl border border-[#dfe5e1] bg-[#eef1ef] sm:min-h-[420px]">
        {error ? (
          <div className="absolute inset-0 grid place-items-center p-6">
            <div role="alert" className="max-w-sm text-center">
              <p className="text-sm font-medium text-[#8a3a2e]">预览加载失败</p>
              <p className="mt-1 text-xs leading-relaxed text-[#7b6a64]">{error}</p>
              {onRetry && (
                <button
                  type="button"
                  onClick={onRetry}
                  className="mt-3 min-h-9 rounded-lg border border-[#e6bdb7] bg-white px-3 text-xs font-medium text-[#8a3a2e] hover:bg-[#fff7f5] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                >
                  重试渲染
                </button>
              )}
            </div>
          </div>
        ) : originalUrl === null ? (
          <div className="absolute inset-0 grid place-items-center p-6 text-center">
            <div>
              <p className="text-sm font-medium text-[#5f6d66]">先上传一张照片</p>
              <p className="mt-1 text-xs text-[#8a9690]">分析完成后即可生成风格方案与真实预览。</p>
            </div>
          </div>
        ) : (
          <>
            {activeView !== "original" && hasResult && (
              // eslint-disable-next-line @next/next/no-img-element -- previews are served by the API
              <img
                src={resultUrl ?? ""}
                alt="风格处理结果"
                className="absolute inset-0 h-full w-full object-contain"
                draggable={false}
                onError={onImageError}
              />
            )}
            {activeView !== "result" && (
              // eslint-disable-next-line @next/next/no-img-element -- previews are served by the API
              <img
                src={originalUrl}
                alt="原图"
                className="absolute inset-0 h-full w-full object-contain"
                style={
                  activeView === "split" && hasResult
                    ? { clipPath: `inset(0 ${100 - split}% 0 0)` }
                    : undefined
                }
                draggable={false}
                onError={onImageError}
              />
            )}
            {activeView === "split" && hasResult && (
              <>
                <div
                  aria-hidden="true"
                  className="pointer-events-none absolute inset-y-0 w-px bg-white shadow-[0_0_0_1px_rgba(39,122,104,.55)]"
                  style={{ left: `${split}%` }}
                />
                <span className="absolute left-3 top-3 rounded-full border border-[rgba(255,255,255,0.4)] bg-[rgba(0,0,0,0.35)] px-2 py-0.5 text-[10px] text-[#f7faf8]">
                  原图
                </span>
                <span className="absolute right-3 top-3 rounded-full border border-[rgba(255,255,255,0.4)] bg-[rgba(0,0,0,0.35)] px-2 py-0.5 text-[10px] text-[#f7faf8]">
                  处理结果
                </span>
              </>
            )}
            {loading && (
              <div className="absolute inset-0 grid place-items-center bg-[rgba(255,255,255,0.55)] backdrop-blur-[2px]">
                <span className="inline-flex items-center gap-2 rounded-full border border-[#d7dfda] bg-white px-3 py-1.5 text-xs text-[#4f5f57]">
                  <span className="size-3 animate-spin rounded-full border-2 border-[#277a68] border-r-transparent" />
                  正在渲染真实预览…
                </span>
              </div>
            )}
          </>
        )}
      </div>

      <div className="flex items-center gap-3">
        <span className="font-mono text-[10px] text-[#8a9690]">原图</span>
        <input
          type="range"
          min={0}
          max={100}
          step={1}
          value={split}
          disabled={!hasResult || activeView !== "split"}
          aria-label="对比分割线位置"
          aria-valuetext={`原图占 ${split}%`}
          onChange={(event) => setSplit(Number(event.target.value))}
          className="h-6 min-w-0 flex-1 accent-[#277a68] disabled:opacity-40"
        />
        <span className="font-mono text-[10px] text-[#8a9690]">结果</span>
      </div>

      {zoomed && resultUrl && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="放大查看处理结果"
          className="fixed inset-0 z-50 flex flex-col bg-[#0d1412]/92 p-3 sm:p-6"
        >
          <div className="mb-2 flex items-center justify-between gap-3 text-[#f7faf8]/75">
            <p className="text-xs">放大查看 · 拖动滑块调整比例</p>
            <button
              type="button"
              onClick={() => setZoomed(false)}
              className="min-h-9 rounded-lg border border-[rgba(255,255,255,0.3)] px-3 text-xs text-[#f7faf8]/80 hover:bg-[rgba(255,255,255,0.1)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              关闭
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-auto rounded-xl border border-[rgba(255,255,255,0.14)] bg-[rgba(0,0,0,0.3)]">
            {/* eslint-disable-next-line @next/next/no-img-element -- previews are served by the API */}
            <img
              src={resultUrl}
              alt="放大后的处理结果"
              className="mx-auto max-w-none"
              style={{ width: `${zoom * 100}%` }}
            />
          </div>
          <label className="mt-3 flex items-center gap-3 text-[11px] text-[#f7faf8]/60">
            缩放
            <input
              type="range"
              min={1}
              max={3}
              step={0.1}
              value={zoom}
              onChange={(event) => setZoom(Number(event.target.value))}
              className="min-w-0 flex-1 accent-[#7fc3ac]"
              aria-label="缩放比例"
              aria-valuetext={`${Math.round(zoom * 100)}%`}
            />
            <span className="w-12 text-right font-mono">{Math.round(zoom * 100)}%</span>
          </label>
        </div>
      )}
    </section>
  );
}
