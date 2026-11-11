"use client";

import { useId, useState } from "react";

import { GenerativeMaskSelect } from "./generative-mask-select";
import { GenerativeTaskResult } from "./generative-task-result";
import { GenerativeTaskStatus } from "./generative-task-status";
import { useGenerativeCapabilities } from "../use-generative-capabilities";
import { useGenerativeMasks } from "../use-generative-masks";
import { useGenerativeTask } from "../use-generative-task";
import type { SessionState } from "@/types/session";

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
  const [instruction, setInstruction] = useState("");

  const capabilities = useGenerativeCapabilities();
  const masks = useGenerativeMasks(sessionId, initialMaskId);

  const generative = useGenerativeTask({
    onAccepted: onResultAccepted,
    onRejected: onResultRejected,
    copy: {
      submitFailed: "提交消除任务失败，请检查网络或参数。",
      retryFailed: "重试消除任务失败，请稍后再试。",
      acceptFailed: "采纳消除结果失败，版本未发生变化。",
      rejectFailed: "放弃消除结果失败，请稍后再试。",
      taskFailed: "消除任务未成功完成。",
    },
  });

  const handleStartTask = async () => {
    if (!masks.selectedMaskId) {
      generative.notify("请先选择或绘制消除蒙版");
      return;
    }
    await generative.submit({
      sessionId,
      taskType: "remove",
      baseMode: "base",
      instruction: instruction.trim() || "remove marked object",
      maskId: masks.selectedMaskId,
      consent: true,
      params: { candidates: 1 },
    });
  };

  return (
    <section
      aria-labelledby={`${panelId}-heading`}
      className="flex flex-col gap-6 p-5 bg-neutral-900 border border-neutral-800 rounded-xl text-neutral-100"
    >
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

      <GenerativeMaskSelect
        sessionId={sessionId}
        masks={masks.masks}
        selectedMaskId={masks.selectedMaskId}
        label="选择消除区域蒙版"
        emptyHint="当前会话暂无蒙版，请点击上方「绘制新蒙版」进行涂抹。"
        imageUrl={imageUrl}
        baseWidth={baseWidth}
        baseHeight={baseHeight}
        onSelect={masks.selectMask}
        onMaskCreated={masks.addMask}
      />

      <div className="flex flex-col gap-1.5">
        <label htmlFor={`${panelId}-prompt`} className="text-xs font-medium text-neutral-300">
          消除指示提示词（可选）
        </label>
        <input
          id={`${panelId}-prompt`}
          type="text"
          value={instruction}
          onChange={(event) => setInstruction(event.target.value)}
          placeholder="例如：消除背景路人，自然补齐山峦与绿植纹理"
          maxLength={1000}
          className="w-full bg-neutral-950 border border-neutral-700 rounded-lg px-3 py-2 text-xs text-neutral-200 placeholder:text-neutral-600 focus:outline-none focus:border-sky-500"
        />
      </div>

      {generative.error && (
        <div
          role="alert"
          aria-live="polite"
          className="p-3 bg-red-950/60 border border-red-800 rounded-lg text-xs text-red-300 flex items-start gap-2"
        >
          <span className="font-semibold">错误:</span>
          <span className="flex-1">{generative.error}</span>
        </div>
      )}

      {generative.isRunning && generative.stage && (
        <GenerativeTaskStatus
          stage={generative.stage}
          labels={STAGE_LABELS}
          onCancel={() => void generative.cancel()}
        />
      )}

      {generative.candidates.map((result) => (
        <GenerativeTaskResult
          key={result.resultId}
          result={result}
          title="消除候选结果已就绪"
          alt="消除后的图像候选"
          badge="保护区 100% 原始字节恢复"
          acceptLabel="采纳消除结果并推进版本"
          acceptingLabel="正在推进版本..."
          busy={generative.isAccepting}
          onAccept={(resultId) => void generative.accept(resultId)}
          onReject={(resultId) => void generative.reject(resultId)}
        />
      ))}

      {!generative.candidates.length && (
        <div className="flex flex-col gap-2">
          {generative.status === "failed" ? (
            <button
              type="button"
              onClick={() => void generative.retry()}
              disabled={generative.isSubmitting}
              className="w-full py-2.5 px-4 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:bg-neutral-800 disabled:text-neutral-500 text-white text-xs font-semibold shadow transition-colors flex items-center justify-center gap-2"
            >
              <span>重试消除任务</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void handleStartTask()}
              disabled={
                !masks.selectedMaskId || generative.isSubmitting || generative.isRunning
              }
              className="w-full py-2.5 px-4 rounded-lg bg-sky-600 hover:bg-sky-500 disabled:bg-neutral-800 disabled:text-neutral-500 disabled:cursor-not-allowed text-white text-xs font-semibold shadow transition-colors flex items-center justify-center gap-2"
            >
              <span>{generative.isSubmitting ? "正在提交任务..." : "开始 AI 智能消除"}</span>
            </button>
          )}
        </div>
      )}
    </section>
  );
}
