import { ApiClientError } from "@/lib/api/client";

export type GenerativeErrorCategory =
  | "network"
  | "provider"
  | "image_format"
  | "mask"
  | "size_limit"
  | "task_limit"
  | "generation_failed"
  | "save_failed";

export interface GenerativeErrorView {
  /** null for client-side guidance notes that never reached the API. */
  category: GenerativeErrorCategory | null;
  label: string;
  message: string;
  nextStep: string;
  code: string | null;
  requestId: string | null;
}

const CATEGORY_META: Record<GenerativeErrorCategory, { label: string; nextStep: string }> = {
  network: {
    label: "网络错误",
    nextStep: "确认后端 API 已启动并可访问，稍后重新提交任务。",
  },
  provider: {
    label: "Provider 错误",
    nextStep: "在设置中检查 Provider 地址、密钥、额度与限流，然后重试任务。",
  },
  image_format: {
    label: "图片格式错误",
    nextStep: "改用单帧 JPEG / PNG / WebP 照片重新上传，再发起生成任务。",
  },
  mask: {
    label: "蒙版错误",
    nextStep: "重新绘制或重新选择蒙版，确保选区落在画面内并保留足够保护区。",
  },
  size_limit: {
    label: "超出尺寸限制",
    nextStep: "减小扩图比例或边距，降低输出像素后再提交。",
  },
  task_limit: {
    label: "超出任务限制",
    nextStep: "按提示补齐任务条件（指令、蒙版、授权、候选数）后重新提交。",
  },
  generation_failed: {
    label: "生成失败",
    nextStep: "重试任务；连续失败时换一种提示词或缩小改动范围。",
  },
  save_failed: {
    label: "保存失败",
    nextStep: "检查磁盘空间与数据目录权限后重试；原始照片不会被覆盖。",
  },
};

interface CodeEntry {
  category: GenerativeErrorCategory;
  message: string;
  nextStep?: string;
}

const CODE_ENTRIES: Record<string, CodeEntry> = {
  // Transport and availability.
  request_timeout: { category: "network", message: "请求超时，后端可能正在处理其他任务。" },
  network_error: { category: "network", message: "无法连接后端服务。" },
  origin_not_allowed: {
    category: "network",
    message: "当前页面来源未被 API 允许。",
    nextStep: "检查 FRAME_ALLOWED_ORIGINS 是否包含本页地址。",
  },
  generative_timeout: {
    category: "network",
    message: "生成任务超时，Provider 未在时限内返回结果。",
    nextStep: "重试任务；持续超时请降低改动幅度或改用响应更快的 Provider。",
  },
  generative_unavailable: {
    category: "network",
    message: "生成服务当前不可用。",
    nextStep: "确认已配置 Provider 与密钥，或启用模拟 Provider 后再试。",
  },

  // Provider side.
  generative_provider_error: { category: "provider", message: "生成 Provider 返回错误。" },
  generative_provider_failed: { category: "provider", message: "Provider 判定本次生成失败。" },
  generative_provider_auth_failed: {
    category: "provider",
    message: "Provider 鉴权失败，密钥无效或已过期。",
    nextStep: "在设置中更新 Provider 密钥后重试。",
  },
  generative_provider_endpoint_error: {
    category: "provider",
    message: "Provider 接口地址不可用。",
    nextStep: "核对 Provider Base URL 与模型名称。",
  },
  generative_provider_invalid_response: {
    category: "provider",
    message: "Provider 返回了无法解析的响应。",
  },
  generative_provider_rate_limited: {
    category: "provider",
    message: "Provider 触发限流，本次请求被拒绝。",
    nextStep: "稍等片刻再提交，或在 Provider 侧提高调用频率上限。",
  },
  generative_provider_timeout: { category: "provider", message: "Provider 响应超时。" },
  generative_provider_unavailable: { category: "provider", message: "Provider 暂时不可用。" },
  generative_provider_usage_unavailable: {
    category: "provider",
    message: "Provider 用量统计接口不可用。",
  },
  generative_provider_budget_exceeded: {
    category: "provider",
    message: "已达到每日 Provider 调用预算。",
    nextStep: "明天再试，或在设置中调高每日限额。",
  },
  generative_provider_response_too_large: {
    category: "provider",
    message: "Provider 返回的内容过大，已被拒绝。",
    nextStep: "减少候选数或降低目标画幅尺寸。",
  },

  // Input image.
  generative_invalid_input: {
    category: "image_format",
    message: "输入图片无法解码，或不符合生成任务的格式要求。",
  },
  invalid_image: { category: "image_format", message: "图片内容已损坏，无法解码。" },
  unsupported_media_type: {
    category: "image_format",
    message: "该图片格式不受支持，请使用 JPEG、PNG 或 WebP。",
  },
  animated_not_supported: {
    category: "image_format",
    message: "动图（多帧 GIF / WebP）暂不支持生成任务。",
  },
  mime_mismatch: {
    category: "image_format",
    message: "文件实际内容与扩展名不一致，已拒绝读取。",
  },
  empty_file: { category: "image_format", message: "上传的文件为空。" },

  // Size limits.
  generative_input_too_large: {
    category: "size_limit",
    message: "输入图片超过 Provider 可处理的最大尺寸。",
  },
  generative_output_too_large: {
    category: "size_limit",
    message: "生成结果超过允许的像素上限。",
  },
  generative_invalid_output_size: {
    category: "size_limit",
    message: "目标画幅尺寸超出允许范围。",
  },
  image_too_many_pixels: {
    category: "size_limit",
    message: "图片像素总数超出后端限制。",
  },

  // Masks.
  generative_mask_missing: { category: "mask", message: "蒙版已被清理或不再可用。" },
  generative_mask_not_found: { category: "mask", message: "找不到该蒙版。" },
  generative_mask_required: { category: "mask", message: "这个任务必须选择或绘制蒙版。" },
  generative_mask_empty: { category: "mask", message: "蒙版是空的，尚未涂抹任何区域。" },
  generative_mask_invalid: { category: "mask", message: "蒙版数据无效。" },
  generative_mask_definition_invalid: {
    category: "mask",
    message: "蒙版形状定义无法解析。",
  },
  generative_mask_coverage: {
    category: "mask",
    message: "蒙版覆盖率不符合任务要求，保护区不足。",
    nextStep: "缩小涂抹范围，保留至少 5% 的未选中区域。",
  },
  generative_mask_mismatch: { category: "mask", message: "蒙版与当前照片不匹配。" },
  generative_mask_size_mismatch: {
    category: "mask",
    message: "蒙版尺寸与当前画面尺寸不一致。",
  },
  generative_mask_conflict: {
    category: "mask",
    message: "蒙版正被其他任务占用，或已被更新。",
  },
  generative_mask_kind_unsupported: {
    category: "mask",
    message: "该蒙版类型不被当前 Provider 支持。",
  },
  generative_mask_semantic_base_unsupported: {
    category: "mask",
    message: "该语义蒙版不能用在当前底图上。",
  },
  generative_mask_service: { category: "mask", message: "蒙版栅格化处理失败。" },

  // Task conditions and quotas.
  generative_capability_unsupported: {
    category: "task_limit",
    message: "当前 Provider 不支持这个生成能力。",
    nextStep: "更换 Provider，或改用工具区中其它可用的生成能力。",
  },
  generative_consent_required: {
    category: "task_limit",
    message: "需要先确认「允许把画面发送到外部 Provider」才能继续。",
  },
  generative_instruction_required: {
    category: "task_limit",
    message: "这个任务需要填写生成指令。",
  },
  generative_outpaint_invalid: {
    category: "task_limit",
    message: "扩图参数不合法，无法组成有效的目标画幅。",
  },
  generative_outpaint_params_required: {
    category: "task_limit",
    message: "扩图任务缺少外扩边距或目标比例。",
  },
  generative_retry_not_allowed: {
    category: "task_limit",
    message: "该任务当前状态不允许重试。",
    nextStep: "重新提交一次新的生成任务。",
  },
  generative_task_not_found: {
    category: "task_limit",
    message: "找不到这个生成任务，可能已过期或被清理。",
  },
  generative_task_not_ready: {
    category: "task_limit",
    message: "任务尚未完成，暂时无法取得结果。",
  },
  generative_result_not_found: { category: "task_limit", message: "找不到这个候选结果。" },
  generative_result_not_candidate: {
    category: "task_limit",
    message: "该结果已被采纳或放弃，无法重复操作。",
  },
  generative_base_changed: {
    category: "task_limit",
    message: "画面已有更新的版本，本次任务基于旧图，已中止。",
    nextStep: "基于最新版本重新提交生成任务。",
  },
  server_busy: {
    category: "task_limit",
    message: "服务器内存不足或正在处理另一张高清图，请稍后再试。",
  },
  validation_error: { category: "task_limit", message: "参数超出允许范围，任务未提交。" },

  // Generation outcome.
  generative_blank_output: { category: "generation_failed", message: "生成结果为空白画面。" },
  generative_empty_output: { category: "generation_failed", message: "生成结果为空数据。" },
  generative_invalid_output: { category: "generation_failed", message: "生成结果不是有效图片。" },
  generative_no_visible_change: {
    category: "generation_failed",
    message: "生成结果与原图没有可见差异。",
    nextStep: "换一种更具体的提示词，或扩大改动区域后重试。",
  },
  generative_service: { category: "generation_failed", message: "生成服务内部处理失败。" },
  generative_internal_error: { category: "generation_failed", message: "服务出现未预期错误。" },

  // Persistence.
  generative_storage_error: {
    category: "save_failed",
    message: "生成结果写入本机存储失败。",
  },
  generative_mask_storage_error: { category: "save_failed", message: "蒙版文件写入失败。" },
  generative_result_corrupted: {
    category: "save_failed",
    message: "候选结果文件已损坏，无法读取。",
  },
  storage_error: { category: "save_failed", message: "服务保存数据失败。" },
};

export interface GenerativeErrorInput {
  code?: string | null;
  message?: string | null;
  requestId?: string | null;
}

function shortRequestId(requestId: string): string {
  return requestId.length > 8 ? requestId.slice(0, 8) : requestId;
}

function readInput(error: unknown): GenerativeErrorInput | null {
  if (error instanceof ApiClientError) {
    return { code: error.code, message: error.message, requestId: error.requestId ?? null };
  }
  if (typeof error === "string") {
    return { message: error };
  }
  if (error instanceof Error) {
    return { message: error.message };
  }
  if (error && typeof error === "object") {
    const record = error as Record<string, unknown>;
    const code = typeof record.code === "string" ? record.code : null;
    const message = typeof record.message === "string" ? record.message : null;
    const requestId = typeof record.requestId === "string" ? record.requestId : null;
    if (code === null && message === null) {
      return null;
    }
    return { code, message, requestId };
  }
  return null;
}

/**
 * Turns whatever a generative call failed with into the eight product categories
 * the studio promises, each paired with the action the user can take next.
 */
export function describeGenerativeError(error: unknown): GenerativeErrorView | null {
  const input = readInput(error);
  if (input === null) {
    return null;
  }

  const code = input.code ?? null;
  const entry = code ? CODE_ENTRIES[code] : undefined;
  const message = input.message?.trim() || "";

  // A hint without a code never left the browser, so it is guidance, not a fault.
  if (!code && !entry) {
    return {
      category: null,
      label: "提示",
      message: message || "请检查参数后重试。",
      nextStep: "",
      code: null,
      requestId: null,
    };
  }

  const category: GenerativeErrorCategory = entry?.category ?? "generation_failed";
  const meta = CATEGORY_META[category];

  return {
    category,
    label: meta.label,
    message: entry?.message || message || `${meta.label}，请稍后重试。`,
    nextStep: entry?.nextStep ?? meta.nextStep,
    code,
    requestId: input.requestId ? shortRequestId(input.requestId) : null,
  };
}
