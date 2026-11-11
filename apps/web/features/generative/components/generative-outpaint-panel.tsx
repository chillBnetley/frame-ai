"use client";

import { useId, useMemo, useState } from "react";

import { computeOutpaintGeometry } from "@/lib/generative-canvas";
import type { SessionState } from "@/types/session";
import { GenerativeTaskResult } from "./generative-task-result";
import { GenerativeTaskStatus } from "./generative-task-status";
import { OutpaintParamsForm, type OutpaintFormValues } from "./outpaint-params-form";
import { useGenerativeCapabilities } from "../use-generative-capabilities";
import { useGenerativeTask } from "../use-generative-task";

export interface GenerativeOutpaintPanelProps {
  sessionId: string;
  baseWidth?: number;
  baseHeight?: number;
  maskId?: string | null;
  onResultAccepted?: (newState: SessionState) => void;
  onResultRejected?: () => void;
}

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

const INITIAL_VALUES: OutpaintFormValues = {
  aspectRatio: null,
  alignment: "center",
  margins: { top: 0, bottom: 0, left: 0, right: 0 },
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
  const [values, setValues] = useState<OutpaintFormValues>(INITIAL_VALUES);
  const [instruction, setInstruction] = useState("");
  const capabilities = useGenerativeCapabilities();

  const generative = useGenerativeTask({
    onAccepted: onResultAccepted,
    onRejected: onResultRejected,
    copy: {
      submitFailed: "提交画幅扩充任务失败，请检查网络或参数。",
      retryFailed: "重试扩图任务失败，请稍后再试。",
      acceptFailed: "采纳扩图结果失败，版本未发生变化。",
      rejectFailed: "放弃扩图结果失败，请稍后再试。",
      taskFailed: "画幅扩充处理失败，请重试。",
    },
  });

  const geometry = useMemo(
    () =>
      computeOutpaintGeometry({
        baseWidth,
        baseHeight,
        margins: values.margins,
        aspectRatio: values.aspectRatio,
        alignment: values.alignment,
      }),
    [baseWidth, baseHeight, values],
  );

  const handleStartOutpaint = async () => {
    if (!geometry.isExpanded) {
      generative.notify("请选择画幅比例或增加至少一个方向的外扩边距。");
      return;
    }

    await generative.submit({
      sessionId,
      taskType: "outpaint",
      instruction: instruction.trim(),
      maskId: maskId ?? null,
      consent: true,
      params: {
        candidates: 1,
        outpaint: {
          top: geometry.top,
          bottom: geometry.bottom,
          left: geometry.left,
          right: geometry.right,
          aspectRatio: values.aspectRatio,
          alignment: values.alignment,
        },
      },
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

      <OutpaintParamsForm
        values={values}
        onChange={setValues}
        baseWidth={baseWidth}
        baseHeight={baseHeight}
        disabled={generative.isRunning}
      />

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
          onChange={(event) => setInstruction(event.target.value)}
          className="w-full bg-neutral-950 border border-neutral-700 rounded-lg px-3 py-2 text-xs text-neutral-200 placeholder:text-neutral-600 focus:outline-none focus:border-sky-500"
        />
      </div>

      {generative.isRunning && generative.stage && (
        <GenerativeTaskStatus
          stage={generative.stage}
          labels={STAGE_LABELS}
          cancelLabel="取消任务"
          onCancel={() => void generative.cancel()}
        />
      )}

      {generative.error && (
        <div
          role="alert"
          aria-live="polite"
          className="bg-rose-950/30 border border-rose-800/50 rounded-lg p-3 text-xs text-rose-300"
        >
          {generative.error}
        </div>
      )}

      {generative.candidates.map((result) => (
        <GenerativeTaskResult
          key={result.resultId}
          result={result}
          title="扩图候选结果已就绪"
          alt="扩图候选预览"
          acceptLabel="采纳新画幅并推进版本"
          acceptingLabel="正在采纳新版本..."
          busy={generative.isAccepting}
          onAccept={(resultId) => void generative.accept(resultId)}
          onReject={(resultId) => void generative.reject(resultId)}
        />
      ))}

      {!generative.candidates.length && (
        <div className="flex flex-col gap-2">
          {generative.status === "failed" ? (
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => void generative.retry()}
                disabled={generative.isSubmitting}
                className="py-2 px-4 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:bg-neutral-800 disabled:text-neutral-500 text-white text-xs font-semibold transition-colors"
              >
                重试 AI 画幅扩充
              </button>
              <button
                type="button"
                onClick={generative.reset}
                className="py-2 px-3 text-xs text-neutral-400 hover:text-neutral-200"
              >
                清除
              </button>
            </div>
          ) : (
            <button
              type="button"
              disabled={generative.isSubmitting || !geometry.isExpanded}
              onClick={() => void handleStartOutpaint()}
              className="w-full py-2.5 px-4 rounded-lg bg-sky-600 hover:bg-sky-500 disabled:bg-neutral-800 disabled:text-neutral-500 disabled:cursor-not-allowed text-white text-xs font-semibold shadow transition-colors flex items-center justify-center gap-2"
            >
              {generative.isSubmitting ? (
                <>
                  <span className="w-3.5 h-3.5 border-2 border-white/20 border-t-white rounded-full animate-spin" />
                  <span>正在生成新画幅...</span>
                </>
              ) : (
                <span>开始 AI 画幅扩充</span>
              )}
            </button>
          )}
        </div>
      )}
    </section>
  );
}
