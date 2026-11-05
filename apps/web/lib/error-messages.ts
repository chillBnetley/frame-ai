import { ApiClientError } from "@/lib/api/client";

export interface EditorError {
  code: string;
  message: string;
  details: Record<string, unknown>;
  requestId?: string | null;
}

export const ERROR_FALLBACK_MESSAGE = "操作未完成，请重试。";

const EDITOR_MESSAGES: Record<string, string> = {
  validation_error: "有参数超出范围，已恢复到上次有效值。",
  revision_conflict: "编辑状态已更新，已为你刷新。",
  idempotency_key_reuse: "保存请求与已有版本冲突，请重试。",
  nothing_to_undo: "没有可撤销的步骤。",
  nothing_to_redo: "没有可重做的步骤。",
  session_not_found: "找不到这张图片或会话，可能已被清理。请重新上传。",
  image_not_found: "找不到这张图片或会话，可能已被清理。请重新上传。",
  revision_not_found: "找不到这个编辑版本，已为你刷新。",
  not_found: "服务接口不存在，可能是后端版本过旧。请重启 API 后重试。",
  server_busy: "服务器内存不足或正在处理另一张高清导出，请稍后几秒再试。",
  preview_expired: "",
  render_superseded: "",
  request_timeout: "请求超时，请稍后重试。",
  network_error: "无法连接后端服务。请确认已启动 API。",
  storage_error: "服务保存数据失败，请稍后重试。",
  internal_error: "服务出现未预期错误，请稍后重试。",
  http_error: "请求失败，请稍后重试。",
};

export function validationFields(details: Record<string, unknown>): string[] {
  const direct = [details.field, details.fieldName, details.path];
  const names = direct.filter((name): name is string => typeof name === "string" && name !== "");
  if (Array.isArray(details.fields)) {
    for (const entry of details.fields) {
      if (isRecord(entry) && typeof entry.field === "string") {
        names.push(entry.field);
      }
    }
  }
  return names;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function validationField(details: Record<string, unknown>): string | null {
  return validationFields(details)[0] ?? null;
}

function shortRequestId(requestId: string): string {
  return requestId.length > 8 ? requestId.slice(0, 8) : requestId;
}

export function editorErrorMessage(
  code: string,
  details: Record<string, unknown> = {},
  requestId: string | null = null,
): string {
  if (code === "export_too_large") {
    const estimated = details.estimatedPeakMb;
    const limit = details.limitMb;
    if (typeof estimated === "number" && typeof limit === "number") {
      return `这张图在当前调整下导出需要约 ${estimated} MB 内存，超过上限 ${limit} MB。可以减少调整项、选择更小的导出长边，或调高 FRAME_EXPORT_MAX_RSS_MB。`;
    }
    return "这张图在当前调整下导出所需内存超过上限。可以减少调整项、选择更小的导出长边，或调高 FRAME_EXPORT_MAX_RSS_MB。";
  }
  const base = EDITOR_MESSAGES[code];
  if (code === "validation_error") {
    const field = validationField(details);
    if (field) {
      return `有参数超出范围，已恢复到上次有效值（${field}）。`;
    }
    return base ?? "有参数超出范围，已恢复到上次有效值。";
  }
  if (base !== undefined) {
    return base;
  }
  const codeSuffix = code && code !== "unknown_error" ? `（错误码：${code}）` : "";
  const requestSuffix = requestId ? `（请求 ID：${shortRequestId(requestId)}）` : "";
  return `发生未知错误，请稍后重试。${codeSuffix}${requestSuffix}`;
}

export function isSilentEditorError(code: string): boolean {
  return code === "preview_expired" || code === "render_superseded";
}

export function describeEditorError(error: unknown): EditorError {
  if (error instanceof ApiClientError) {
    const described: EditorError = {
      code: error.code,
      message: editorErrorMessage(error.code, error.details, error.requestId),
      details: error.details,
    };
    if (error.requestId) {
      described.requestId = error.requestId;
    }
    return described;
  }
  if (error instanceof Error) {
    return { code: "unknown_error", message: error.message, details: {} };
  }
  return { code: "unknown_error", message: "发生未知错误，请稍后重试。", details: {} };
}
