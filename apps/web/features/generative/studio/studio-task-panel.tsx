"use client";

import { useEffect, useId } from "react";

import { GenerativeMaskSelect } from "../components/generative-mask-select";
import { GenerativeTaskResult } from "../components/generative-task-result";
import { OutpaintParamsForm } from "../components/outpaint-params-form";
import type { GenerativeSuggestion } from "../suggestions";
import { buildStyleInstruction } from "../style-instruction";
import { useGenerativeStorage } from "../use-generative-storage";
import { StudioSuggestions } from "./studio-suggestions";
import { STUDIO_CAPABILITIES } from "./studio-tool-rail";
import type { CreativeStudioController } from "./use-creative-studio";
import { createGenerativeMask } from "@/lib/api/generative";
import { formatBytes } from "@/lib/format";
import type { GenerativeBaseMode } from "@/types/generative";

export interface StudioTaskPanelProps {
  controller: CreativeStudioController;
  sessionId: string;
  imageUrl: string | null;
  baseWidth: number;
  baseHeight: number;
  suggestions: GenerativeSuggestion[];
}

const SUBMIT_LABELS: Record<string, string> = {
  outpaint: "开始 AI 画幅扩充",
  remove: "开始 AI 智能消除",
  local_edit: "开始 AI 局部生成",
};

const BUSY_LABELS: Record<string, string> = {
  outpaint: "正在生成新画幅...",
  remove: "正在消除标记内容...",
  local_edit: "正在重绘选定区域...",
};

const RETRY_LABELS: Record<string, string> = {
  outpaint: "重试 AI 画幅扩充",
  remove: "重试消除任务",
  local_edit: "重试局部生成任务",
};

const RESULT_TITLES: Record<string, string> = {
  outpaint: "扩图候选结果已就绪",
  remove: "消除候选结果已就绪",
  local_edit: "局部生成候选结果已就绪",
};

const ACCEPT_LABELS: Record<string, string> = {
  outpaint: "采纳新画幅并推进版本",
  remove: "采纳消除结果并推进版本",
  local_edit: "采纳局部生成结果并推进版本",
};

const PROMPT_FIELDS: Record<
  string,
  { label: string; placeholder: string; required: boolean; multiline: boolean }
> = {
  outpaint: {
    label: "扩图指示提示词（可选）",
    placeholder: "例如：向外延展宁静的雪山山峦与通透的清晨天际线",
    required: false,
    multiline: false,
  },
  remove: {
    label: "消除指示提示词（可选）",
    placeholder: "例如：消除背景路人，自然补齐山峦与绿植纹理",
    required: false,
    multiline: false,
  },
  local_edit: {
    label: "生成指令（必填）",
    placeholder: "例如：把墙面换成风化砖墙，保持原有阴天光线",
    required: true,
    multiline: true,
  },
};

const MASK_SECTION: Record<string, { label: string; emptyHint: string; coverage: string }> = {
  remove: {
    label: "选择消除区域蒙版",
    emptyHint: "当前会话暂无蒙版，请点击上方「绘制新蒙版」进行涂抹。",
    coverage: "覆盖率",
  },
  local_edit: {
    label: "选择编辑区域蒙版（必填）",
    emptyHint: "当前会话暂无蒙版，请点击上方「绘制新蒙版」圈出要修改的区域。",
    coverage: "编辑区覆盖率",
  },
};

const FIELD_CLASS =
  "w-full bg-neutral-950 border border-neutral-700 rounded-lg px-3 py-2 text-xs text-neutral-200 placeholder:text-neutral-600 focus:outline-none focus:border-sky-500 disabled:opacity-50";

const BASE_MODES: { value: GenerativeBaseMode; label: string; hint: string }[] = [
  {
    value: "base",
    label: "当前基准",
    hint: "直接使用当前版本的基准像素（原图或已采纳的生成图）。",
  },
  {
    value: "graded",
    label: "已调色版本",
    hint: "先把当前调色压平成一张全分辨率图，再作为生成输入与保护区写回基准；原图文件不变。",
  },
];

const GRADED_UNAVAILABLE_HINT =
  "当前版本含裁切或旋转，已调色基准暂不可用；请先撤销裁切/旋转，或继续使用当前基准。";

export function StudioTaskPanel({
  controller,
  sessionId,
  imageUrl,
  baseWidth,
  baseHeight,
  suggestions,
}: StudioTaskPanelProps) {
  const panelId = useId();
  const { studio, capability, task, masks, geometry, capabilities, validationMessage, canSubmit } =
    controller;
  const { baseMode, gradedBaseAvailable, styleOptions, subjectMaskAvailable } = controller;
  const { storage, reload: reloadStorage } = useGenerativeStorage();
  const state = studio.state;
  const meta = STUDIO_CAPABILITIES.find((item) => item.value === capability);
  const prompt = PROMPT_FIELDS[capability];
  const maskSection = MASK_SECTION[capability];

  useEffect(() => {
    if (task.status === "succeeded" || task.candidates.length === 0) {
      reloadStorage();
    }
  }, [task.status, task.candidates.length, reloadStorage]);

  const isBudgetExceeded = Boolean(storage && storage.usedBytes >= storage.limitBytes);
  const effectiveCanSubmit = canSubmit && !isBudgetExceeded;
  const effectiveValidationMessage = isBudgetExceeded
    ? "生成式存储已达上限，请删除不需要的照片或等待临时候选过期。"
    : validationMessage;

  const applySuggestion = (suggestion: GenerativeSuggestion): void => {
    if (suggestion.capability) {
      studio.setCapability(suggestion.capability);
    }
    if (suggestion.instruction) {
      studio.setStyleId(null);
      studio.setInstruction(suggestion.instruction);
    }
  };

  const applyStyle = (styleId: string): void => {
    const style = styleOptions.find((item) => item.id === styleId) ?? null;
    studio.setStyleId(style?.id ?? null);
    if (style) {
      studio.setInstruction(buildStyleInstruction(style));
    }
  };

  const createSubjectMask = async (suggestion: GenerativeSuggestion): Promise<void> => {
    const region = suggestion.subjectBbox;
    if (!region) {
      return;
    }
    const created = await createGenerativeMask({
      sessionId,
      kind: "rect",
      definition: { region, expand: 0 },
      feather: 0,
      inverted: false,
    });
    masks.addMask(created);
  };

  return (
    <section
      aria-labelledby={`${panelId}-heading`}
      className="flex flex-col gap-5 p-4 rounded-xl border border-neutral-800 bg-neutral-900 text-neutral-100"
    >
      <div className="flex items-start justify-between gap-3 border-b border-neutral-800 pb-3">
        <div>
          <h2 id={`${panelId}-heading`} className="text-sm font-medium tracking-wide">
            {meta?.label ?? "生成参数"}
          </h2>
          <p className="mt-0.5 text-[11px] leading-relaxed text-neutral-400">{meta?.hint}</p>
        </div>
        {capabilities?.isMock && (
          <span className="shrink-0 text-[11px] px-2 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/20">
            模拟生成模式
          </span>
        )}
      </div>

      <StudioSuggestions
        suggestions={suggestions}
        disabled={task.isRunning}
        onApply={applySuggestion}
        onCreateSubjectMask={subjectMaskAvailable ? createSubjectMask : undefined}
      />

      <div className="flex flex-col gap-2">
        <label id={`${panelId}-base-mode-label`} className="text-xs font-medium text-neutral-300">
          输入基准
        </label>
        <div
          role="radiogroup"
          aria-labelledby={`${panelId}-base-mode-label`}
          className="grid grid-cols-2 gap-2"
        >
          {BASE_MODES.map((item) => {
            const isSelected = baseMode === item.value;
            return (
              <button
                key={item.value}
                type="button"
                role="radio"
                aria-checked={isSelected}
                disabled={task.isRunning || (item.value === "graded" && !gradedBaseAvailable)}
                onClick={() => studio.setBaseMode(item.value)}
                className={`py-1.5 px-3 text-xs rounded-lg border transition-all disabled:opacity-50 disabled:cursor-not-allowed ${
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
        <p className="text-[11px] leading-relaxed text-neutral-400">
          {gradedBaseAvailable
            ? BASE_MODES.find((item) => item.value === baseMode)?.hint
            : GRADED_UNAVAILABLE_HINT}
        </p>
      </div>

      {capability === "outpaint" && (
        <OutpaintParamsForm
          values={state.outpaint}
          onChange={studio.setOutpaint}
          baseWidth={baseWidth}
          baseHeight={baseHeight}
          disabled={task.isRunning}
        />
      )}

      {maskSection && (
        <GenerativeMaskSelect
          sessionId={sessionId}
          masks={masks.masks}
          selectedMaskId={masks.selectedMaskId}
          label={maskSection.label}
          emptyHint={maskSection.emptyHint}
          coverageLabel={maskSection.coverage}
          imageUrl={imageUrl}
          baseWidth={baseWidth}
          baseHeight={baseHeight}
          onSelect={masks.selectMask}
          onMaskCreated={masks.addMask}
        />
      )}

      {capability === "local_edit" &&
        (styleOptions.length > 0 ? (
          <div className="flex flex-col gap-1.5">
            <label htmlFor={`${panelId}-style`} className="text-xs font-medium text-neutral-300">
              我的风格（Visual DNA）
            </label>
            <select
              id={`${panelId}-style`}
              value={state.styleId ?? ""}
              disabled={task.isRunning}
              onChange={(event) => applyStyle(event.target.value)}
              className={FIELD_CLASS}
            >
              <option value="">不使用风格</option>
              {styleOptions.map((style) => (
                <option key={style.id} value={style.id}>
                  {style.name}
                </option>
              ))}
            </select>
            <p className="text-[11px] leading-relaxed text-neutral-400">
              选择后只把风格描述填入生成指令，可继续编辑；不会自动提交任务。
            </p>
          </div>
        ) : (
          <p className="text-[11px] leading-relaxed text-neutral-400">
            我的风格：Visual DNA 中暂无已发布并启用的个人风格，可直接手写生成指令。
          </p>
        ))}

      <div className="flex flex-col gap-1.5">
        <label htmlFor={`${panelId}-prompt`} className="text-xs font-medium text-neutral-300">
          {prompt.label}
        </label>
        {prompt.multiline ? (
          <textarea
            id={`${panelId}-prompt`}
            rows={3}
            maxLength={2000}
            value={state.instruction}
            disabled={task.isRunning}
            placeholder={prompt.placeholder}
            onChange={(event) => studio.setInstruction(event.target.value)}
            className={`${FIELD_CLASS} resize-y`}
          />
        ) : (
          <input
            id={`${panelId}-prompt`}
            type="text"
            maxLength={1000}
            value={state.instruction}
            disabled={task.isRunning}
            placeholder={prompt.placeholder}
            onChange={(event) => studio.setInstruction(event.target.value)}
            className={FIELD_CLASS}
          />
        )}
        {prompt.required && (
          <p className="text-[11px] text-neutral-400">
            指令只作用于蒙版区域；蒙版需保留至少 5% 的保护区，否则任务会被拒绝。
          </p>
        )}
      </div>

      {capabilities && (
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 rounded-lg border border-neutral-800 bg-neutral-950/60 p-3 text-[11px] text-neutral-400">
          <dt>Provider</dt>
          <dd className="truncate text-right text-neutral-200">{capabilities.model}</dd>
          <dt>最长边上限</dt>
          <dd className="text-right font-mono text-neutral-200">{capabilities.maxLongEdge}px</dd>
          <dt>输出像素上限</dt>
          <dd className="text-right font-mono text-neutral-200">
            {capabilities.maxOutputPixels.toLocaleString("en-US")}
          </dd>
          <dt>多候选</dt>
          <dd className="text-right text-neutral-200">
            {capabilities.supportsMultipleOutputs ? "支持" : "单次 1 张"}
          </dd>
        </dl>
      )}

      <div className="flex flex-col gap-2">
        {task.status === "failed" ? (
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => void task.retry()}
              disabled={task.isSubmitting}
              className="flex-1 py-2.5 px-4 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:bg-neutral-800 disabled:text-neutral-500 text-white text-xs font-semibold transition-colors"
            >
              {RETRY_LABELS[capability]}
            </button>
            <button
              type="button"
              onClick={task.reset}
              className="py-2 px-3 text-xs text-neutral-400 hover:text-neutral-200"
            >
              清除
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => void controller.submitTask()}
            disabled={task.isSubmitting || task.isRunning || !effectiveCanSubmit}
            className="w-full py-2.5 px-4 rounded-lg bg-sky-600 hover:bg-sky-500 disabled:bg-neutral-800 disabled:text-neutral-500 disabled:cursor-not-allowed text-white text-xs font-semibold shadow transition-colors flex items-center justify-center gap-2"
          >
            {task.isSubmitting || task.isRunning ? (
              <>
                <span className="w-3.5 h-3.5 border-2 border-white/20 border-t-white rounded-full animate-spin" />
                <span>{BUSY_LABELS[capability]}</span>
              </>
            ) : (
              <span>{SUBMIT_LABELS[capability]}</span>
            )}
          </button>
        )}

        {effectiveValidationMessage && task.status !== "failed" && (
          <p className="text-[11px] leading-relaxed text-amber-300">{effectiveValidationMessage}</p>
        )}

        <p className="text-[11px] leading-relaxed text-neutral-500">
          提交即同意将当前画面与蒙版发送到已配置的 Provider
          {capabilities ? `（${capabilities.declaredRetention}）` : ""}；
          {baseMode === "graded"
            ? "原图文件保持不变，保护区按压平后的已调色像素逐字节写回。"
            : "原图与保护区像素不会被覆盖。"}
          {state.styleId ? "风格指令会随画面一起发送到该 Provider。" : ""}
          {capability === "outpaint" && geometry.isExpanded
            ? ` 目标画幅 ${geometry.targetWidth} × ${geometry.targetHeight}。`
            : ""}
        </p>
      </div>

      {storage && (
        <div
          data-testid="generative-storage-meter"
          className="rounded-lg border border-neutral-800 bg-neutral-950/60 p-2.5 text-[11px] text-neutral-400 flex flex-col gap-1.5"
        >
          <div className="flex items-center justify-between font-mono text-[11px]">
            <span className="text-neutral-400">本机 AI 存储预算</span>
            <span
              className={
                storage.usedBytes >= storage.limitBytes
                  ? "text-rose-400 font-semibold"
                  : storage.usedBytes / storage.limitBytes >= 0.8
                    ? "text-amber-300 font-medium"
                    : "text-neutral-300"
              }
            >
              {formatBytes(storage.usedBytes)} / {formatBytes(storage.limitBytes)}
            </span>
          </div>
          <div className="w-full bg-neutral-800 h-1.5 rounded-full overflow-hidden">
            <div
              className={`h-full transition-all ${
                storage.usedBytes >= storage.limitBytes
                  ? "bg-rose-500"
                  : storage.usedBytes / storage.limitBytes >= 0.8
                    ? "bg-amber-400"
                    : "bg-sky-500"
              }`}
              style={{
                width: `${Math.min(100, Math.round((storage.usedBytes / Math.max(1, storage.limitBytes)) * 100))}%`,
              }}
            />
          </div>
          {storage.usedBytes >= storage.limitBytes ? (
            <p className="text-[10px] text-rose-300 leading-tight">
              存储预算已耗尽，请删除不需要的照片或等待临时候选过期后重试。
            </p>
          ) : storage.usedBytes / storage.limitBytes >= 0.8 ? (
            <p className="text-[10px] text-amber-300 leading-tight">
              存储已使用超过 80%，临时候选结果保留 {storage.retentionDays} 天。
            </p>
          ) : null}
        </div>
      )}

      {task.candidates.map((result) => (
        <GenerativeTaskResult
          key={result.resultId}
          result={result}
          title={RESULT_TITLES[capability]}
          alt={`${meta?.label ?? "生成"}候选预览`}
          acceptLabel={ACCEPT_LABELS[capability]}
          acceptingLabel="正在采纳新版本..."
          busy={task.isAccepting}
          onAccept={(resultId) => void controller.acceptResult(resultId)}
          onReject={(resultId) => void controller.rejectResult(resultId)}
        />
      ))}
    </section>
  );
}
