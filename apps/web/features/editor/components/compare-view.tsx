"use client";

import { useEffect, useState } from "react";

import { compareSession } from "@/lib/api/sessions";
import { describeEditorError } from "@/lib/error-messages";
import type { CompareResponse } from "@/types/session";

export interface CompareViewProps {
  sessionId: string;
  revisionId: string;
  dirty: boolean;
  onClose: () => void;
}

interface CompareDataState {
  key: string;
  data: CompareResponse;
}

interface CompareErrorState {
  key: string;
  message: string;
}

export function CompareView({
  sessionId,
  revisionId,
  dirty,
  onClose,
}: CompareViewProps) {
  const [attempt, setAttempt] = useState(0);
  const [dataState, setDataState] = useState<CompareDataState | null>(null);
  const [errorState, setErrorState] = useState<CompareErrorState | null>(null);
  const [split, setSplit] = useState(50);
  const [holding, setHolding] = useState(false);

  const key = `${revisionId}:${attempt}`;

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    compareSession(sessionId, { revisionId }, controller.signal)
      .then((response) => {
        if (!cancelled) {
          setDataState({ key, data: response });
          setErrorState(null);
        }
      })
      .catch((error: unknown) => {
        if (!cancelled && !controller.signal.aborted) {
          setDataState(null);
          setErrorState({ key, message: describeEditorError(error).message });
        }
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [key, revisionId, sessionId]);

  const data = dataState?.key === key ? dataState.data : null;
  const error = errorState?.key === key ? errorState.message : null;
  const loading = data === null && error === null;
  const aspectMismatch =
    data !== null &&
    data.revision.height > 0 &&
    data.original.height > 0 &&
    Math.abs(
      data.original.width / data.original.height -
        data.revision.width / data.revision.height,
    ) /
      (data.revision.width / data.revision.height) >
      0.01;
  const imageFitClass = aspectMismatch ? "object-contain" : "object-fill";

  return (
    <section aria-labelledby="compare-heading" className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h4 id="compare-heading" className="text-xs font-medium text-white/80">
            前后对比
          </h4>
          <p className="mt-0.5 text-[10px] text-white/35">
            左侧：原图（仅应用旋转/裁切），右侧：编辑版本。
            {dirty ? " 当前有未保存的调整，对比基于已保存版本。" : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            aria-pressed={holding}
            onPointerDown={(event) => {
              event.preventDefault();
              setHolding(true);
            }}
            onPointerUp={() => setHolding(false)}
            onPointerLeave={() => setHolding(false)}
            onPointerCancel={() => setHolding(false)}
            onKeyDown={(event) => {
              if (event.key === " " || event.key === "Enter") {
                event.preventDefault();
                setHolding(true);
              }
            }}
            onKeyUp={(event) => {
              if (event.key === " " || event.key === "Enter") {
                setHolding(false);
              }
            }}
            className="min-h-11 rounded-lg border border-white/15 bg-white/[0.04] px-3 text-xs text-white/75 transition-colors hover:bg-white/[0.08] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent aria-pressed:border-accent/40 aria-pressed:bg-accent/10 aria-pressed:text-accent"
          >
            {holding ? "正在查看原图" : "按住查看原图"}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="min-h-11 rounded-lg px-3 text-xs text-white/50 transition-colors hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            退出对比
          </button>
        </div>
      </div>

      <p role="status" aria-live="polite" className="sr-only">
        {loading ? "正在生成对比图…" : error ? `对比图加载失败：${error}` : "对比图已就绪。"}
      </p>

      {error ? (
        <div
          role="alert"
          className="flex flex-col items-center gap-3 rounded-xl border border-red-400/25 bg-red-400/[0.06] px-6 py-12 text-center"
        >
          <p className="text-xs text-red-100">{error}</p>
          <button
            type="button"
            onClick={() => setAttempt((value) => value + 1)}
            className="min-h-11 rounded-lg border border-red-300/25 bg-red-300/10 px-3 text-xs text-red-100 transition-colors hover:bg-red-300/20 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-200"
          >
            重新加载对比图
          </button>
        </div>
      ) : loading || data === null ? (
        <div className="flex min-h-64 items-center justify-center rounded-xl border border-white/8 bg-black/35">
          <p className="text-xs text-white/45">正在生成对比图…</p>
        </div>
      ) : (
        <div className="grid gap-2">
          <div
            className="relative select-none overflow-hidden rounded-xl bg-black ring-1 ring-white/10"
            style={{ aspectRatio: `${data.revision.width} / ${data.revision.height}` }}
          >
            {!holding && (
              // eslint-disable-next-line @next/next/no-img-element -- content-addressed previews are served by the API
              <img
                src={data.revision.previewUrl}
                alt="编辑后的版本"
                className={`absolute inset-0 h-full w-full ${imageFitClass}`}
                draggable={false}
              />
            )}
            {/* eslint-disable-next-line @next/next/no-img-element -- content-addressed previews are served by the API */}
            <img
              src={data.original.previewUrl}
              alt="原图"
              className={`absolute inset-0 h-full w-full ${imageFitClass}`}
              style={holding ? undefined : { clipPath: `inset(0 ${100 - split}% 0 0)` }}
              draggable={false}
            />
            {!holding && (
              <div
                aria-hidden="true"
                className="pointer-events-none absolute inset-y-0 w-px bg-accent/80"
                style={{ left: `${split}%` }}
              />
            )}
            {holding && (
              <span className="absolute left-3 top-3 rounded-full border border-white/20 bg-black/65 px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.14em] text-white/80">
                原图
              </span>
            )}
          </div>

          <div className="flex items-center gap-3">
            <span className="font-mono text-[10px] text-white/35">原图</span>
            <input
              type="range"
              min={0}
              max={100}
              step={1}
              value={split}
              aria-label="对比分割线位置"
              aria-valuetext={`原图占 ${split}%`}
              onChange={(event) => setSplit(Number(event.target.value))}
              className="h-6 min-w-0 flex-1 accent-[#d8ff5f]"
            />
            <span className="font-mono text-[10px] text-white/35">编辑版本</span>
          </div>
          <p className="text-[10px] text-white/30">
            {data.revision.width} × {data.revision.height}
          </p>
          {aspectMismatch && (
            <p className="text-[10px] text-amber-200/70">
              原图与编辑版本比例不同，已按完整画布显示以避免拉伸。
            </p>
          )}
        </div>
      )}
    </section>
  );
}
