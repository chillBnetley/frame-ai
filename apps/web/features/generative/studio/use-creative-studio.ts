"use client";

import { useCallback, useMemo } from "react";

import { computeOutpaintGeometry, type OutpaintGeometry } from "@/lib/generative-canvas";
import { generativeMaskImageUrl } from "@/lib/api/generative";
import type {
  GenerativeBaseMode,
  GenerativeCapabilitiesResponse,
  GenerativeTaskRequest,
} from "@/types/generative";
import type { SessionState } from "@/types/session";
import type { OutpaintFormValues } from "../components/outpaint-params-form";
import { useGenerativeCapabilities } from "../use-generative-capabilities";
import { useGenerativeMasks, type GenerativeMasksController } from "../use-generative-masks";
import { useGenerativeTask, type GenerativeTaskController } from "../use-generative-task";
import { usePersonalStyleOptions } from "../use-personal-style-options";
import { useStudioState, type StudioCapability, type StudioController } from "./use-studio-state";
import type { PersonalStyleItem } from "@/types/personal-style";

export interface CreativeStudioOptions {
  sessionId: string;
  baseWidth: number;
  baseHeight: number;
  gradedBaseAvailable: boolean;
  initialMaskId?: string | null;
  initialCapability?: StudioCapability;
  /** False when the base is a generated asset, so analysis bboxes no longer line up. */
  subjectMaskAvailable?: boolean;
  onResultAccepted?: (state: SessionState) => void;
  onResultRejected?: () => void;
}

export interface StudioValidationInput {
  capability: StudioCapability;
  baseMode: GenerativeBaseMode;
  gradedBaseAvailable: boolean;
  instruction: string;
  maskId: string | null;
  geometry: OutpaintGeometry;
  capabilities: GenerativeCapabilitiesResponse | null;
}

const OUTPAINT_NEEDS_FRAME_MESSAGE = "请选择画幅比例或增加至少一个方向的外扩边距。";
const GRADED_BASE_UNAVAILABLE_MESSAGE =
  "当前版本含裁切或旋转，无法用已调色版本作为生成基准，请改用当前基准。";

/**
 * Client-side gate for the failures that never need a round-trip: missing
 * inputs and target sizes the provider cannot serve. Anything else is left to
 * the backend so the message the user reads is the real reason.
 */
export function validateStudioRequest(input: StudioValidationInput): string | null {
  const prompt = input.instruction.trim();

  if (input.baseMode === "graded" && !input.gradedBaseAvailable) {
    return GRADED_BASE_UNAVAILABLE_MESSAGE;
  }

  if (input.capability === "outpaint") {
    if (!input.geometry.isExpanded) {
      return OUTPAINT_NEEDS_FRAME_MESSAGE;
    }
    const caps = input.capabilities;
    if (caps) {
      const longEdge = Math.max(input.geometry.targetWidth, input.geometry.targetHeight);
      if (caps.maxLongEdge > 0 && longEdge > caps.maxLongEdge) {
        return `目标画幅的最长边 ${longEdge}px 超过当前 Provider 上限 ${caps.maxLongEdge}px，请减小比例或边距。`;
      }
      const pixels = input.geometry.targetWidth * input.geometry.targetHeight;
      if (caps.maxOutputPixels > 0 && pixels > caps.maxOutputPixels) {
        return `目标画幅共 ${pixels} 像素，超过当前 Provider 上限 ${caps.maxOutputPixels} 像素，请减小比例或边距。`;
      }
    }
    return null;
  }

  if (input.capability === "local_edit" && !prompt) {
    return "请填写生成指令，例如：把墙面换成风化砖墙";
  }
  if (!input.maskId) {
    return input.capability === "remove"
      ? "请先选择或绘制消除区域蒙版。"
      : "请先选择或绘制局部编辑蒙版。";
  }
  return null;
}

export function buildStudioTaskRequest(
  input: StudioValidationInput & {
    sessionId: string;
    outpaint: OutpaintFormValues;
  },
): GenerativeTaskRequest {
  const prompt = input.instruction.trim();

  if (input.capability === "outpaint") {
    return {
      sessionId: input.sessionId,
      taskType: "outpaint",
      baseMode: input.baseMode,
      instruction: prompt,
      maskId: input.maskId,
      consent: true,
      params: {
        candidates: 1,
        outpaint: {
          top: input.geometry.top,
          bottom: input.geometry.bottom,
          left: input.geometry.left,
          right: input.geometry.right,
          aspectRatio: input.outpaint.aspectRatio,
          alignment: input.outpaint.alignment,
        },
      },
    };
  }

  return {
    sessionId: input.sessionId,
    taskType: input.capability,
    baseMode: input.baseMode,
    instruction: input.capability === "remove" ? prompt || "remove marked object" : prompt,
    maskId: input.maskId,
    consent: true,
    params: { candidates: 1 },
  };
}

const CAPABILITY_STAGE_LABELS: Record<StudioCapability, Record<string, string>> = {
  outpaint: {
    queued: "排队中...",
    preparing_input: "正在合成扩展画布与保护蒙版...",
    submitting: "正在提交至生成引擎...",
    generating: "AI 正在绘制扩充画面...",
    validating: "正在执行像素级保护区写回与校验...",
    saving: "正在保存画幅候选...",
    completed: "扩图完成",
    failed: "扩图未成功",
  },
  remove: {
    queued: "排队中...",
    preparing_input: "正在锁定保护区与合成待修区域...",
    submitting: "正在提交至生成引擎...",
    generating: "AI 正在重绘背景以消除标记内容...",
    validating: "正在执行保护区 100% 原始字节恢复校验...",
    saving: "正在保存消除候选...",
    completed: "消除完成",
    failed: "消除未成功",
  },
  local_edit: {
    queued: "排队中...",
    preparing_input: "正在解析画面与锁定保护区...",
    submitting: "正在提交至生成模型...",
    generating: "AI 正在按指令重绘选定区域...",
    validating: "正在执行未选区域字节级写回与校验...",
    saving: "正在保存生成候选...",
    completed: "局部生成完成",
    failed: "局部生成未成功",
  },
};

const CAPABILITY_COPY: Record<
  StudioCapability,
  {
    submitFailed: string;
    retryFailed: string;
    acceptFailed: string;
    rejectFailed: string;
    taskFailed: string;
  }
> = {
  outpaint: {
    submitFailed: "提交画幅扩充任务失败，请检查网络或参数。",
    retryFailed: "重试扩图任务失败，请稍后再试。",
    acceptFailed: "采纳扩图结果失败，版本未发生变化。",
    rejectFailed: "放弃扩图结果失败，请稍后再试。",
    taskFailed: "画幅扩充处理失败，请重试。",
  },
  remove: {
    submitFailed: "提交消除任务失败，请检查网络或参数。",
    retryFailed: "重试消除任务失败，请稍后再试。",
    acceptFailed: "采纳消除结果失败，版本未发生变化。",
    rejectFailed: "放弃消除结果失败，请稍后再试。",
    taskFailed: "画幅消除处理失败，请重试。",
  },
  local_edit: {
    submitFailed: "提交局部生成任务失败，请检查网络或参数。",
    retryFailed: "重试局部生成任务失败，请稍后再试。",
    acceptFailed: "采纳局部生成结果失败，版本未发生变化。",
    rejectFailed: "放弃局部生成结果失败，请稍后再试。",
    taskFailed: "局部生成任务未成功完成。",
  },
};

export interface CreativeStudioController {
  studio: StudioController;
  capability: StudioCapability;
  baseMode: GenerativeBaseMode;
  gradedBaseAvailable: boolean;
  stageLabels: Record<string, string>;
  baseWidth: number;
  baseHeight: number;
  geometry: OutpaintGeometry;
  masks: GenerativeMasksController;
  maskImageUrl: string | null;
  capabilities: GenerativeCapabilitiesResponse | null;
  styleOptions: PersonalStyleItem[];
  subjectMaskAvailable: boolean;
  task: GenerativeTaskController;
  validationMessage: string | null;
  canSubmit: boolean;
  submitTask: () => Promise<boolean>;
  acceptResult: (resultId: string) => Promise<boolean>;
  rejectResult: (resultId: string) => Promise<boolean>;
}

export function useCreativeStudio(options: CreativeStudioOptions): CreativeStudioController {
  const {
    sessionId,
    baseWidth,
    baseHeight,
    gradedBaseAvailable,
    initialMaskId = null,
    initialCapability,
    subjectMaskAvailable = false,
    onResultAccepted,
    onResultRejected,
  } = options;

  const studio = useStudioState(initialCapability);
  const capabilities = useGenerativeCapabilities();
  const styleOptions = usePersonalStyleOptions();
  const masks = useGenerativeMasks(sessionId, initialMaskId);
  const capability = studio.state.capability;
  // A crop/rotation recipe cannot be flattened without reprojection, so the
  // switch falls back to the untouched base instead of sending a bad request.
  const baseMode: GenerativeBaseMode = gradedBaseAvailable ? studio.state.baseMode : "base";

  const task = useGenerativeTask({
    copy: CAPABILITY_COPY[capability],
    onAccepted: onResultAccepted,
    onRejected: onResultRejected,
  });
  const { submit, notify, accept, reject } = task;

  const geometry = useMemo(
    () =>
      computeOutpaintGeometry({
        baseWidth,
        baseHeight,
        margins: studio.state.outpaint.margins,
        aspectRatio: studio.state.outpaint.aspectRatio,
        alignment: studio.state.outpaint.alignment,
      }),
    [baseWidth, baseHeight, studio.state.outpaint],
  );

  const validationMessage = validateStudioRequest({
    capability,
    baseMode,
    gradedBaseAvailable,
    instruction: studio.state.instruction,
    maskId: masks.selectedMaskId,
    geometry,
    capabilities,
  });

  const submitTask = useCallback(async (): Promise<boolean> => {
    if (validationMessage !== null) {
      notify(validationMessage);
      return false;
    }
    return submit(
      buildStudioTaskRequest({
        sessionId,
        capability,
        baseMode,
        gradedBaseAvailable,
        instruction: studio.state.instruction,
        maskId: masks.selectedMaskId,
        geometry,
        capabilities,
        outpaint: studio.state.outpaint,
      }),
    );
  }, [
    baseMode,
    capabilities,
    capability,
    geometry,
    gradedBaseAvailable,
    masks.selectedMaskId,
    notify,
    sessionId,
    studio.state.instruction,
    studio.state.outpaint,
    submit,
    validationMessage,
  ]);

  const acceptResult = useCallback(
    async (resultId: string): Promise<boolean> => accept(resultId),
    [accept],
  );

  const rejectResult = useCallback(
    async (resultId: string): Promise<boolean> => reject(resultId),
    [reject],
  );

  const maskImageUrl = masks.selectedMaskId ? generativeMaskImageUrl(masks.selectedMaskId) : null;

  return {
    studio,
    capability,
    baseMode,
    gradedBaseAvailable,
    stageLabels: CAPABILITY_STAGE_LABELS[capability],
    baseWidth,
    baseHeight,
    geometry,
    masks,
    maskImageUrl,
    capabilities,
    styleOptions,
    subjectMaskAvailable,
    task,
    validationMessage,
    canSubmit: validationMessage === null,
    submitTask,
    acceptResult,
    rejectResult,
  };
}

export type { StudioCapability };
