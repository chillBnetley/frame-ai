"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import {
  acceptGenerativeResult,
  cancelGenerativeTask,
  createGenerativeTask,
  generativeResultImageUrl,
  getGenerativeCapabilities,
  pollGenerativeTask,
  rejectGenerativeResult,
  retryGenerativeTask,
} from "@/lib/api/generative";
import type {
  GenerativeCapabilitiesResponse,
  GenerativeOutpaintAlignment,
  GenerativeResultView,
  GenerativeTaskStatusResponse,
} from "@/types/generative";
import type { SessionState } from "@/types/session";

export interface GenerativeOutpaintPanelProps {
  sessionId: string;
  baseWidth?: number;
  baseHeight?: number;
  maskId?: string | null;
  onResultAccepted?: (newState: SessionState) => void;
  onResultRejected?: () => void;
}

const PRESET_RATIOS = [
  { label: "自由边距", value: null },
  { label: "1:1", value: "1:1" },
  { label: "16:9", value: "16:9" },
  { label: "9:16", value: "9:16" },
  { label: "4:3", value: "4:3" },
  { label: "3:4", value: "3:4" },
  { label: "3:2", value: "3:2" },
  { label: "2:3", value: "2:3" },
  { label: "21:9", value: "21:9" },
] as const;

const ALIGNMENTS: { label: string; value: GenerativeOutpaintAlignment }[] = [
  { label: "居中", value: "center" },
  { label: "靠上", value: "top" },
  { label: "靠下", value: "bottom" },
  { label: "靠左", value: "left" },
  { label: "靠右", value: "right" },
];

const STAGE_LABELS: Record<string, string> = {
  queued: "排队中...",
  preparing_input: "正在合成扩展画布与保护蒙版...",
  submitting: "正在提交至生成引擎...",
  generating: "AI 正在绘制扩充画面...",
  validating: "正在执行像素级保护区写回与校验...",
  saving: "正在保存画幅候选...",
  completed: "扩图完成",
  failed: "扩图未成功",
};

export function GenerativeOutpaintPanel({
  sessionId,
  baseWidth = 1920,
  baseHeight = 1080,
  maskId = null,
  onResultAccepted,
  onResultRejected,
}: GenerativeOutpaintPanelProps) {
  const panelId = useId();
  const [selectedRatio, setSelectedRatio] = useState<string | null>(null);
  const [alignment, setAlignment] = useState<GenerativeOutpaintAlignment>("center");

  // Pixel margins
  const [topMargin, setTopMargin] = useState(0);
  const [bottomMargin, setBottomMargin] = useState(0);
  const [leftMargin, setLeftMargin] = useState(0);
  const [rightMargin, setRightMargin] = useState(0);

  const [instruction, setInstruction] = useState("");
  const [capabilities, setCapabilities] = useState<GenerativeCapabilitiesResponse | null>(null);

  // Task execution state
  const [activeTask, setActiveTask] = useState<GenerativeTaskStatusResponse | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isAccepting, setIsAccepting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    getGenerativeCapabilities(ctrl.signal)
      .then(setCapabilities)
      .catch(() => {
        // Mock fallback if offline/disconnected
      });
    return () => ctrl.abort();
  }, []);

  // Compute calculated dimensions based on ratio or margins
  const calculated = useMemo(() => {
    let top = topMargin;
    let bottom = bottomMargin;
    let left = leftMargin;
    let right = rightMargin;

    if (selectedRatio) {
      const parts = selectedRatio.split(":");
      const rw = Number.parseFloat(parts[0] || "1");
      const rh = Number.parseFloat(parts[1] || "1");

      const curW = baseWidth + left + right;
      const curH = baseHeight + top + bottom;

      let targetW: number;
      let targetH: number;

      if (rw * curH >= rh * curW) {
        targetH = curH;
        targetW = Math.ceil((curH * rw) / rh);
      } else {
        targetW = curW;
        targetH = Math.ceil((curW * rh) / rw);
      }

      const extraW = targetW - curW;
      const extraH = targetH - curH;

      if (alignment === "left") {
        right += extraW;
      } else if (alignment === "right") {
        left += extraW;
      } else {
        const leftHalf = Math.floor(extraW / 2);
        left += leftHalf;
        right += extraW - leftHalf;
      }

      if (alignment === "top") {
        bottom += extraH;
      } else if (alignment === "bottom") {
        top += extraH;
      } else {
        const topHalf = Math.floor(extraH / 2);
        top += topHalf;
        bottom += extraH - topHalf;
      }
    }

    const targetW = baseWidth + left + right;
    const targetH = baseHeight + top + bottom;
    const isExpanded = targetW > baseWidth || targetH > baseHeight;

    return {
      top,
      bottom,
      left,
      right,
      targetW,
      targetH,
      isExpanded,
    };
  }, [selectedRatio, alignment, topMargin, bottomMargin, leftMargin, rightMargin, baseWidth, baseHeight]);

  const handleStartOutpaint = useCallback(async () => {
    if (!calculated.isExpanded) {
      setErrorMsg("请选择画幅比例或增加至少一个方向的外扩边距。");
      return;
    }

    setErrorMsg(null);
    setIsSubmitting(true);
    abortControllerRef.current?.abort();
    const ctrl = new AbortController();
    abortControllerRef.current = ctrl;

    try {
      const created = await createGenerativeTask(
        {
          sessionId,
          taskType: "outpaint",
          instruction: instruction.trim(),
          maskId: maskId ?? null,
          consent: true,
          params: {
            candidates: 1,
            outpaint: {
              top: calculated.top,
              bottom: calculated.bottom,
              left: calculated.left,
              right: calculated.right,
              aspectRatio: selectedRatio,
              alignment,
            },
          },
        },
        undefined,
        ctrl.signal,
      );

      const completedTask = await pollGenerativeTask(
        created.taskId,
        {
          intervalMs: 300,
          onUpdate: (task) => setActiveTask(task),
        },
        ctrl.signal,
      );

      setActiveTask(completedTask);
      if (completedTask.status === "failed") {
        setErrorMsg(completedTask.error?.message ?? "画幅扩充处理失败，请重试。");
      }
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === "AbortError") {
        return;
      }
      const message =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "提交画幅扩充任务失败，请检查网络或参数。";
      setErrorMsg(message);
    } finally {
      setIsSubmitting(false);
    }
  }, [calculated, sessionId, instruction, maskId, selectedRatio, alignment]);

  const handleCancelTask = useCallback(async () => {
    if (!activeTask?.taskId) return;
    try {
      const updated = await cancelGenerativeTask(activeTask.taskId);
      setActiveTask(updated);
    } catch {
      // Ignored if cancelled
    }
  }, [activeTask]);

  const handleRetryTask = useCallback(async () => {
    if (!activeTask?.taskId) return;
    setIsSubmitting(true);
    setErrorMsg(null);
    try {
      const restarted = await retryGenerativeTask(activeTask.taskId);
      setActiveTask(restarted);
      const pollResult = await pollGenerativeTask(restarted.taskId, {
        intervalMs: 300,
        onUpdate: (t) => setActiveTask(t),
      });
      setActiveTask(pollResult);
    } catch (err: unknown) {
      const message =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "重试失败。";
      setErrorMsg(message);
    } finally {
      setIsSubmitting(false);
    }
  }, [activeTask]);

  const handleAcceptResult = useCallback(
    async (result: GenerativeResultView) => {
      setIsAccepting(true);
      setErrorMsg(null);
      try {
        const state = await acceptGenerativeResult(result.resultId);
        onResultAccepted?.(state);
      } catch (err: unknown) {
        const message =
          typeof err === "object" && err !== null && "message" in err
            ? String((err as { message: unknown }).message)
            : "采纳结果失败。";
        setErrorMsg(message);
      } finally {
        setIsAccepting(false);
      }
    },
    [onResultAccepted],
  );

  const handleRejectResult = useCallback(
    async (result: GenerativeResultView) => {
      setErrorMsg(null);
      try {
        await rejectGenerativeResult(result.resultId);
        setActiveTask(null);
        onResultRejected?.();
      } catch (err: unknown) {
        const message =
          typeof err === "object" && err !== null && "message" in err
            ? String((err as { message: unknown }).message)
            : "放弃结果失败。";
        setErrorMsg(message);
      }
    },
    [onResultRejected],
  );

  const candidate = activeTask?.results?.[0];

  return (
    <section
      aria-labelledby={`${panelId}-heading`}
      className="flex flex-col gap-6 p-5 bg-neutral-900 border border-neutral-800 rounded-xl text-neutral-100"
    >
      <div className="flex items-center justify-between border-b border-neutral-800 pb-3">
        <div>
          <h2 id={`${panelId}-heading`} className="text-base font-medium tracking-wide">
            AI 画幅扩充 (Outpainting)
          </h2>
          <p className="text-xs text-neutral-400 mt-0.5">
            智能向外扩展画面构图与景深，原图保护区 100% 字节级一致。
          </p>
        </div>
        {capabilities?.isMock && (
          <span className="text-[11px] px-2 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/20">
            模拟生成模式
          </span>
        )}
      </div>

      {/* Target Aspect Ratio Selection */}
      <div className="flex flex-col gap-2.5">
        <label id={`${panelId}-ratio-label`} className="text-xs font-medium text-neutral-300">
          目标画幅比例
        </label>
        <div
          role="radiogroup"
          aria-labelledby={`${panelId}-ratio-label`}
          className="grid grid-cols-3 sm:grid-cols-5 gap-2"
        >
          {PRESET_RATIOS.map((item) => {
            const isSelected = selectedRatio === item.value;
            return (
              <button
                key={item.label}
                type="button"
                role="radio"
                aria-checked={isSelected}
                onClick={() => setSelectedRatio(item.value)}
                className={`py-1.5 px-3 text-xs rounded-lg border transition-all ${
                  isSelected
                    ? "bg-sky-600 border-sky-400 text-white shadow-sm font-semibold"
                    : "bg-neutral-800/80 border-neutral-700/80 text-neutral-300 hover:bg-neutral-800 hover:border-neutral-600"
                }`}
              >
                {item.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Alignment when ratio is active */}
      {selectedRatio && (
        <div className="flex flex-col gap-2">
          <label id={`${panelId}-align-label`} className="text-xs font-medium text-neutral-300">
            画面对齐定位
          </label>
          <div
            role="radiogroup"
            aria-labelledby={`${panelId}-align-label`}
            className="flex flex-wrap gap-2"
          >
            {ALIGNMENTS.map((item) => {
              const isSelected = alignment === item.value;
              return (
                <button
                  key={item.value}
                  type="button"
                  role="radio"
                  aria-checked={isSelected}
                  onClick={() => setAlignment(item.value)}
                  className={`py-1 px-3 text-xs rounded-md border transition-colors ${
                    isSelected
                      ? "bg-neutral-200 border-white text-neutral-900 font-semibold"
                      : "bg-neutral-800 border-neutral-700 text-neutral-300 hover:bg-neutral-700"
                  }`}
                >
                  {item.label}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Manual Margins Input */}
      {!selectedRatio && (
        <div className="flex flex-col gap-2">
          <span className="text-xs font-medium text-neutral-300">自定义各向扩展像素 (px)</span>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
            <div>
              <label htmlFor={`${panelId}-top`} className="text-[11px] text-neutral-400 block mb-1">
                向上扩展 (Top)
              </label>
              <input
                id={`${panelId}-top`}
                type="number"
                min={0}
                max={4000}
                value={topMargin}
                onChange={(e) => setTopMargin(Math.max(0, Number.parseInt(e.target.value || "0", 10)))}
                className="w-full bg-neutral-950 border border-neutral-700 rounded px-2.5 py-1 text-xs text-neutral-200 focus:outline-none focus:border-sky-500"
              />
            </div>
            <div>
              <label htmlFor={`${panelId}-bottom`} className="text-[11px] text-neutral-400 block mb-1">
                向下扩展 (Bottom)
              </label>
              <input
                id={`${panelId}-bottom`}
                type="number"
                min={0}
                max={4000}
                value={bottomMargin}
                onChange={(e) => setBottomMargin(Math.max(0, Number.parseInt(e.target.value || "0", 10)))}
                className="w-full bg-neutral-950 border border-neutral-700 rounded px-2.5 py-1 text-xs text-neutral-200 focus:outline-none focus:border-sky-500"
              />
            </div>
            <div>
              <label htmlFor={`${panelId}-left`} className="text-[11px] text-neutral-400 block mb-1">
                向左扩展 (Left)
              </label>
              <input
                id={`${panelId}-left`}
                type="number"
                min={0}
                max={4000}
                value={leftMargin}
                onChange={(e) => setLeftMargin(Math.max(0, Number.parseInt(e.target.value || "0", 10)))}
                className="w-full bg-neutral-950 border border-neutral-700 rounded px-2.5 py-1 text-xs text-neutral-200 focus:outline-none focus:border-sky-500"
              />
            </div>
            <div>
              <label htmlFor={`${panelId}-right`} className="text-[11px] text-neutral-400 block mb-1">
                向右扩展 (Right)
              </label>
              <input
                id={`${panelId}-right`}
                type="number"
                min={0}
                max={4000}
                value={rightMargin}
                onChange={(e) => setRightMargin(Math.max(0, Number.parseInt(e.target.value || "0", 10)))}
                className="w-full bg-neutral-950 border border-neutral-700 rounded px-2.5 py-1 text-xs text-neutral-200 focus:outline-none focus:border-sky-500"
              />
            </div>
          </div>
        </div>
      )}

      {/* Canvas Geometry Layout Preview */}
      <div className="bg-neutral-950/70 border border-neutral-800 rounded-lg p-3 flex flex-col sm:flex-row items-center justify-between gap-4">
        <div className="text-xs space-y-1">
          <div className="text-neutral-400">
            原画尺寸: <span className="text-neutral-200 font-mono">{baseWidth} × {baseHeight}</span>
          </div>
          <div className="text-neutral-400">
            目标尺寸:{" "}
            <span className="text-sky-400 font-mono font-medium">
              {calculated.targetW} × {calculated.targetH}
            </span>{" "}
            <span className="text-[11px] text-neutral-500">
              (+{calculated.targetW - baseWidth}px 宽, +{calculated.targetH - baseHeight}px 高)
            </span>
          </div>
          <div className="text-[11px] text-neutral-500">
            边距: 上 {calculated.top}px · 下 {calculated.bottom}px · 左 {calculated.left}px · 右 {calculated.right}px
          </div>
        </div>

        {/* Scaled Mini Canvas Diagram */}
        <div
          aria-hidden="true"
          className="relative w-28 h-20 bg-sky-950/40 border border-dashed border-sky-600/40 rounded flex items-center justify-center p-1"
        >
          <div
            className="bg-neutral-700 border border-neutral-500 text-[9px] text-neutral-200 flex items-center justify-center rounded-sm transition-all"
            style={{
              width: `${Math.max(20, Math.min(100, (baseWidth / calculated.targetW) * 100))}%`,
              height: `${Math.max(20, Math.min(100, (baseHeight / calculated.targetH) * 100))}%`,
            }}
          >
            原图
          </div>
        </div>
      </div>

      {/* Optional Prompt */}
      <div className="flex flex-col gap-1.5">
        <label htmlFor={`${panelId}-prompt`} className="text-xs font-medium text-neutral-300">
          扩图指示提示词（可选）
        </label>
        <input
          id={`${panelId}-prompt`}
          type="text"
          maxLength={1000}
          placeholder="例如：向外延展宁静的雪山山峦与通透的清晨天际线"
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          className="w-full bg-neutral-950 border border-neutral-700 rounded-lg px-3 py-2 text-xs text-neutral-200 placeholder:text-neutral-600 focus:outline-none focus:border-sky-500"
        />
      </div>

      {/* Action / Progress Area */}
      {isSubmitting && activeTask && (
        <div className="bg-sky-950/20 border border-sky-800/40 rounded-lg p-3 text-xs flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-sky-400 animate-pulse" />
            <span className="text-sky-200">{STAGE_LABELS[activeTask.stage] || "处理中..."}</span>
          </div>
          <button
            type="button"
            onClick={handleCancelTask}
            className="text-xs text-neutral-400 hover:text-neutral-200 underline"
          >
            取消任务
          </button>
        </div>
      )}

      {errorMsg && (
        <div role="alert" className="bg-rose-950/30 border border-rose-800/50 rounded-lg p-3 text-xs text-rose-300">
          {errorMsg}
        </div>
      )}

      {/* Candidate Result Card */}
      {candidate && activeTask?.status === "succeeded" && (
        <div className="border border-neutral-700 bg-neutral-950 rounded-xl p-4 flex flex-col gap-3">
          <div className="flex items-center justify-between text-xs">
            <span className="font-medium text-emerald-400">扩图候选结果已就绪</span>
            <span className="text-neutral-400 font-mono">
              {candidate.width} × {candidate.height}
            </span>
          </div>

          <div className="relative rounded-lg overflow-hidden border border-neutral-800 bg-neutral-900 aspect-auto max-h-72 flex items-center justify-center">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={generativeResultImageUrl(candidate.resultId)}
              alt="扩图候选预览"
              className="max-h-72 w-auto object-contain"
            />
          </div>

          <div className="flex flex-wrap gap-1.5">
            {candidate.warnings?.map((w) => (
              <span
                key={w}
                className="text-[10px] px-2 py-0.5 rounded bg-neutral-800 text-neutral-300 border border-neutral-700"
              >
                {w}
              </span>
            ))}
          </div>

          <div className="flex items-center gap-3 pt-1">
            <button
              type="button"
              disabled={isAccepting}
              onClick={() => handleAcceptResult(candidate)}
              className="flex-1 py-2 px-4 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-xs font-semibold shadow transition-colors"
            >
              {isAccepting ? "正在采纳新版本..." : "采纳新画幅并推进版本"}
            </button>
            <button
              type="button"
              disabled={isAccepting}
              onClick={() => handleRejectResult(candidate)}
              className="py-2 px-4 rounded-lg bg-neutral-800 hover:bg-neutral-700 text-neutral-300 text-xs font-medium transition-colors"
            >
              放弃
            </button>
          </div>
        </div>
      )}

      {/* Failed State Area */}
      {activeTask?.status === "failed" && (
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={handleRetryTask}
            disabled={isSubmitting}
            className="py-2 px-4 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-xs font-medium transition-colors"
          >
            重试扩图
          </button>
          <button
            type="button"
            onClick={() => setActiveTask(null)}
            className="py-2 px-3 text-xs text-neutral-400 hover:text-neutral-200"
          >
            清除
          </button>
        </div>
      )}

      {/* Primary Submit Button */}
      {(!candidate || activeTask?.status !== "succeeded") && (
        <button
          type="button"
          disabled={isSubmitting || !calculated.isExpanded}
          onClick={handleStartOutpaint}
          className="w-full py-2.5 px-4 rounded-lg bg-sky-600 hover:bg-sky-500 disabled:bg-neutral-800 disabled:text-neutral-500 disabled:cursor-not-allowed text-white text-xs font-semibold shadow transition-colors flex items-center justify-center gap-2"
        >
          {isSubmitting ? (
            <>
              <span className="w-3.5 h-3.5 border-2 border-white/20 border-t-white rounded-full animate-spin" />
              <span>正在生成新画幅...</span>
            </>
          ) : (
            <span>开始 AI 画幅扩充</span>
          )}
        </button>
      )}
    </section>
  );
}
