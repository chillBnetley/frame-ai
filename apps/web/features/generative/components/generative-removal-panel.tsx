"use client";

import { useEffect, useId, useRef, useState } from "react";
import {
  acceptGenerativeResult,
  cancelGenerativeTask,
  createGenerativeTask,
  generativeMaskImageUrl,
  generativeResultImageUrl,
  getGenerativeCapabilities,
  listGenerativeMasks,
  pollGenerativeTask,
  rejectGenerativeResult,
  retryGenerativeTask,
} from "@/lib/api/generative";
import type {
  GenerativeCapabilitiesResponse,
  GenerativeMaskView,
  GenerativeResultView,
  GenerativeTaskStatusResponse,
} from "@/types/generative";
import type { SessionState } from "@/types/session";
import { GenerativeMaskEditor } from "./generative-mask-editor";

export interface GenerativeRemovalPanelProps {
  sessionId: string;
  imageUrl?: string | null;
  initialMaskId?: string | null;
  baseWidth?: number;
  baseHeight?: number;
  onResultAccepted?: (newState: SessionState) => void;
  onResultRejected?: () => void;
}

const STAGE_LABELS: Record<string, string> = {
  queued: "排队中...",
  preparing_input: "正在解析画面与锁定保护区...",
  submitting: "正在提交至消除模型...",
  generating: "AI 正在修复消除区域纹理...",
  validating: "正在执行像素级保护区写回与校验...",
  saving: "正在保存消除候选...",
  completed: "消除完成",
  failed: "消除未成功",
};

export function GenerativeRemovalPanel({
  sessionId,
  imageUrl = null,
  initialMaskId = null,
  baseWidth = 1920,
  baseHeight = 1080,
  onResultAccepted,
  onResultRejected,
}: GenerativeRemovalPanelProps) {
  const panelId = useId();
  const [capabilities, setCapabilities] = useState<GenerativeCapabilitiesResponse | null>(null);

  // Mask state
  const [selectedMaskId, setSelectedMaskId] = useState<string | null>(initialMaskId);
  const [availableMasks, setAvailableMasks] = useState<GenerativeMaskView[]>([]);
  const [showMaskEditor, setShowMaskEditor] = useState(false);
  const [instruction, setInstruction] = useState("");

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
      .catch(() => {});

    listGenerativeMasks(sessionId, { limit: 20 }, ctrl.signal)
      .then((resp) => {
        if (!ctrl.signal.aborted) {
          setAvailableMasks(resp.items);
          if (resp.items.length > 0 && !initialMaskId) {
            setSelectedMaskId((prev) => prev || resp.items[0].maskId);
          }
        }
      })
      .catch(() => {});

    return () => ctrl.abort();
  }, [sessionId, initialMaskId]);

  const handleStartTask = async () => {
    if (!selectedMaskId) {
      setErrorMsg("请先选择或绘制消除蒙版");
      return;
    }
    setErrorMsg(null);
    setIsSubmitting(true);
    abortControllerRef.current = new AbortController();

    try {
      const created = await createGenerativeTask(
        {
          sessionId,
          taskType: "remove",
          instruction: instruction.trim() || "remove marked object",
          maskId: selectedMaskId,
          consent: true,
          params: { candidates: 1 },
        },
        undefined,
        abortControllerRef.current.signal,
      );

      const completedTask = await pollGenerativeTask(
        created.taskId,
        {
          intervalMs: 300,
          onUpdate: (task) => setActiveTask(task),
        },
        abortControllerRef.current.signal,
      );

      setActiveTask(completedTask);
      if (completedTask.status === "failed") {
        setErrorMsg(completedTask.error?.message || "消除任务未成功完成");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "提交消除任务失败";
      setErrorMsg(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCancelTask = async () => {
    if (!activeTask?.taskId) return;
    abortControllerRef.current?.abort();
    try {
      const cancelled = await cancelGenerativeTask(activeTask.taskId);
      setActiveTask(cancelled);
    } catch {
      // Ignore cancel error
    }
  };

  const handleRetryTask = async () => {
    if (!activeTask?.taskId) return;
    setErrorMsg(null);
    setIsSubmitting(true);
    abortControllerRef.current = new AbortController();
    try {
      const retried = await retryGenerativeTask(activeTask.taskId);
      setActiveTask(retried);
      const completedTask = await pollGenerativeTask(
        retried.taskId,
        {
          intervalMs: 300,
          onUpdate: (task) => setActiveTask(task),
        },
        abortControllerRef.current.signal,
      );
      setActiveTask(completedTask);
      if (completedTask.status === "failed") {
        setErrorMsg(completedTask.error?.message || "重试任务失败");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "重试任务失败";
      setErrorMsg(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleAcceptResult = async (resultId: string) => {
    setIsAccepting(true);
    try {
      const updatedSession = await acceptGenerativeResult(resultId);
      onResultAccepted?.(updatedSession);
      setActiveTask(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "采纳结果失败";
      setErrorMsg(msg);
    } finally {
      setIsAccepting(false);
    }
  };

  const handleRejectResult = async (resultId: string) => {
    try {
      await rejectGenerativeResult(resultId);
      onResultRejected?.();
      setActiveTask(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "放弃结果失败";
      setErrorMsg(msg);
    }
  };

  const isRunning =
    activeTask !== null &&
    (activeTask.status === "queued" ||
      activeTask.status === "processing" ||
      activeTask.status === "created" ||
      activeTask.status === "validating");

  const candidateResults: GenerativeResultView[] =
    activeTask?.status === "succeeded" && activeTask.results ? activeTask.results : [];

  const selectedMask = availableMasks.find((m) => m.maskId === selectedMaskId);

  return (
    <section
      aria-labelledby={`${panelId}-heading`}
      className="flex flex-col gap-6 p-5 bg-neutral-900 border border-neutral-800 rounded-xl text-neutral-100"
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-neutral-800 pb-3">
        <div>
          <h2 id={`${panelId}-heading`} className="text-base font-medium tracking-wide">
            AI 智能消除 (Object Removal)
          </h2>
          <p className="text-xs text-neutral-400 mt-0.5">
            涂抹不需要的路人或瑕疵，AI 自动修复背景，保护区 100% 字节级一致。
          </p>
        </div>
        {capabilities?.isMock && (
          <span className="text-[11px] px-2 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/20">
            模拟生成模式
          </span>
        )}
      </div>

      {/* Mask Selection / Creation Section */}
      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <label id={`${panelId}-mask-select-label`} className="text-xs font-medium text-neutral-300">
            选择消除区域蒙版
          </label>
          <button
            type="button"
            onClick={() => setShowMaskEditor((prev) => !prev)}
            className="text-xs px-2.5 py-1 rounded bg-neutral-800 hover:bg-neutral-700 text-sky-400 border border-neutral-700 transition-colors"
          >
            {showMaskEditor ? "关闭蒙版画板" : "绘制新蒙版"}
          </button>
        </div>

        {/* Embedded Mask Editor */}
        {showMaskEditor && (
          <div className="border border-neutral-800 rounded-lg p-3 bg-neutral-950">
            <GenerativeMaskEditor
              sessionId={sessionId}
              imageUrl={imageUrl}
              previewWidth={Math.min(baseWidth, 640)}
              previewHeight={Math.min(baseHeight, 480)}
              onMaskCreated={(newMask) => {
                setAvailableMasks((prev) => [newMask, ...prev]);
                setSelectedMaskId(newMask.maskId);
                setShowMaskEditor(false);
              }}
              onClose={() => setShowMaskEditor(false)}
            />
          </div>
        )}

        {/* Mask options list */}
        {availableMasks.length > 0 ? (
          <div
            role="radiogroup"
            aria-labelledby={`${panelId}-mask-select-label`}
            className="grid grid-cols-1 sm:grid-cols-2 gap-2"
          >
            {availableMasks.map((mask) => {
              const isSelected = mask.maskId === selectedMaskId;
              return (
                <button
                  key={mask.maskId}
                  type="button"
                  role="radio"
                  aria-checked={isSelected}
                  onClick={() => setSelectedMaskId(mask.maskId)}
                  className={`flex items-center gap-3 p-2.5 rounded-lg border text-left transition-all ${
                    isSelected
                      ? "bg-sky-950/60 border-sky-500/80 text-white shadow-sm ring-1 ring-sky-500/50"
                      : "bg-neutral-950/40 border-neutral-800 text-neutral-300 hover:border-neutral-700"
                  }`}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={generativeMaskImageUrl(mask.maskId)}
                    alt=""
                    aria-hidden="true"
                    className="w-12 h-12 object-contain bg-neutral-900 border border-neutral-700 rounded"
                  />
                  <div className="flex-1 min-w-0 text-xs">
                    <div className="font-medium truncate capitalize">
                      {mask.kind === "brush" ? "画笔蒙版" : mask.kind === "rect" ? "矩形框选" : mask.kind}
                    </div>
                    <div className="text-[11px] text-neutral-400 mt-0.5">
                      覆盖率: {(mask.quality.coverage * 100).toFixed(1)}%
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        ) : (
          !showMaskEditor && (
            <div className="p-4 text-center rounded-lg border border-dashed border-neutral-800 bg-neutral-950/40 text-neutral-400 text-xs">
              <span>当前会话暂无蒙版，请点击上方「绘制新蒙版」进行涂抹。</span>
            </div>
          )
        )}

        {selectedMask && (
          <div className="text-[11px] text-neutral-400 bg-neutral-950/60 px-3 py-2 rounded border border-neutral-800 flex items-center justify-between">
            <span>当前已选蒙版: {selectedMask.maskId.slice(0, 8)}...</span>
            <span className="text-emerald-400">已就绪</span>
          </div>
        )}
      </div>

      {/* Prompt Instruction Input */}
      <div className="flex flex-col gap-1.5">
        <label htmlFor={`${panelId}-prompt`} className="text-xs font-medium text-neutral-300">
          消除指示提示词（可选）
        </label>
        <input
          id={`${panelId}-prompt`}
          type="text"
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          placeholder="例如：消除背景路人，自然补齐山峦与绿植纹理"
          maxLength={1000}
          className="w-full bg-neutral-950 border border-neutral-700 rounded-lg px-3 py-2 text-xs text-neutral-200 placeholder:text-neutral-600 focus:outline-none focus:border-sky-500"
        />
      </div>

      {/* Error message */}
      {errorMsg && (
        <div
          role="alert"
          aria-live="polite"
          className="p-3 bg-red-950/60 border border-red-800 rounded-lg text-xs text-red-300 flex items-start gap-2"
        >
          <span className="font-semibold">错误:</span>
          <span className="flex-1">{errorMsg}</span>
        </div>
      )}

      {/* Progress & Status */}
      {isRunning && (
        <div
          role="status"
          aria-live="polite"
          className="flex flex-col gap-2 p-3 bg-sky-950/30 border border-sky-800/60 rounded-lg text-xs text-sky-200"
        >
          <div className="flex items-center justify-between">
            <span className="font-medium animate-pulse">
              {STAGE_LABELS[activeTask.stage] || "任务执行中..."}
            </span>
            <button
              type="button"
              onClick={handleCancelTask}
              className="text-xs px-2 py-0.5 rounded bg-neutral-800 hover:bg-neutral-700 text-neutral-300 transition-colors"
            >
              取消
            </button>
          </div>
          <div className="w-full bg-neutral-800 rounded-full h-1.5 overflow-hidden">
            <div className="bg-sky-500 h-1.5 rounded-full animate-indeterminate" />
          </div>
        </div>
      )}

      {/* Candidate Result Inspection */}
      {candidateResults.length > 0 && (
        <div className="flex flex-col gap-3 p-4 bg-neutral-950 border border-neutral-800 rounded-lg">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold text-neutral-200">消除候选结果已就绪</h3>
            <span className="text-[11px] px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              保护区 100% 原始字节恢复
            </span>
          </div>

          {candidateResults.map((result) => (
            <div key={result.resultId} className="flex flex-col gap-3">
              <div className="relative border border-neutral-800 rounded overflow-hidden max-h-80 bg-neutral-900 flex items-center justify-center">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={generativeResultImageUrl(result.resultId)}
                  alt="消除后的图像候选"
                  className="max-h-72 object-contain"
                />
              </div>

              <div className="flex flex-wrap gap-2 justify-end">
                <button
                  type="button"
                  onClick={() => handleRejectResult(result.resultId)}
                  className="px-3 py-1.5 text-xs rounded-lg border border-neutral-700 text-neutral-300 hover:bg-neutral-800 transition-colors"
                >
                  放弃
                </button>
                <button
                  type="button"
                  onClick={() => handleAcceptResult(result.resultId)}
                  disabled={isAccepting}
                  className="px-4 py-1.5 text-xs font-medium rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:bg-neutral-800 disabled:text-neutral-500 text-white shadow-sm transition-colors"
                >
                  {isAccepting ? "正在推进版本..." : "采纳消除结果并推进版本"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Main Execution Trigger Button */}
      {!candidateResults.length && (
        <div className="flex flex-col gap-2">
          {activeTask?.status === "failed" ? (
            <button
              type="button"
              onClick={handleRetryTask}
              disabled={isSubmitting}
              className="w-full py-2.5 px-4 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:bg-neutral-800 disabled:text-neutral-500 text-white text-xs font-semibold shadow transition-colors flex items-center justify-center gap-2"
            >
              <span>重试消除任务</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={handleStartTask}
              disabled={!selectedMaskId || isSubmitting || isRunning}
              className="w-full py-2.5 px-4 rounded-lg bg-sky-600 hover:bg-sky-500 disabled:bg-neutral-800 disabled:text-neutral-500 disabled:cursor-not-allowed text-white text-xs font-semibold shadow transition-colors flex items-center justify-center gap-2"
            >
              <span>{isSubmitting ? "正在提交任务..." : "开始 AI 智能消除"}</span>
            </button>
          )}
        </div>
      )}
    </section>
  );
}
