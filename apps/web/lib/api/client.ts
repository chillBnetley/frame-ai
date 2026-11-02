import type { UploadedImage, HealthResponse, RuntimeConfig } from "@/types/image";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/+$/, "");
const UPLOAD_TIMEOUT_MS = 60_000;
const HEALTH_TIMEOUT_MS = 5_000;
const CONFIG_TIMEOUT_MS = 5_000;
const DEFAULT_TIMEOUT_MS = 30_000;

export class ApiClientError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;

  constructor(
    code: string,
    message: string,
    status = 0,
    details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiClientError";
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

export function originalImageUrl(imageId: string, download = false): string {
  const url = apiUrl(`/api/v1/images/${encodeURIComponent(imageId)}/original`);
  return download ? `${url}?download=true` : url;
}

function createTimeoutSignal(externalSignal: AbortSignal | undefined, timeoutMs: number) {
  const controller = new AbortController();
  const timer = globalThis.setTimeout(() => {
    controller.abort(new DOMException("Request timed out", "TimeoutError"));
  }, timeoutMs);

  const forwardAbort = () => controller.abort(externalSignal?.reason);
  if (externalSignal) {
    if (externalSignal.aborted) {
      forwardAbort();
    } else {
      externalSignal.addEventListener("abort", forwardAbort, { once: true });
    }
  }

  return {
    signal: controller.signal,
    cleanup() {
      globalThis.clearTimeout(timer);
      externalSignal?.removeEventListener("abort", forwardAbort);
    },
  };
}

async function responseToError(response: Response): Promise<ApiClientError> {
  try {
    const payload = (await response.json()) as {
      error?: { code?: unknown; message?: unknown; details?: unknown };
    };
    const code = typeof payload.error?.code === "string" ? payload.error.code : "http_error";
    const message =
      typeof payload.error?.message === "string"
        ? payload.error.message
        : `请求失败（HTTP ${response.status}）`;
    const details =
      payload.error?.details && typeof payload.error.details === "object"
        ? (payload.error.details as Record<string, unknown>)
        : {};
    return new ApiClientError(code, message, response.status, details);
  } catch {
    return new ApiClientError("http_error", `请求失败（HTTP ${response.status}）`, response.status);
  }
}

function normalizeTransportError(error: unknown): ApiClientError {
  if (error instanceof ApiClientError) {
    return error;
  }
  if (error instanceof DOMException && error.name === "TimeoutError") {
    return new ApiClientError("request_timeout", "请求超时，请检查网络或稍后重试。");
  }
  return new ApiClientError("network_error", "无法连接 API 服务，请确认后端已经启动。");
}

export interface ApiRequestOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
}

export async function apiRequest(
  path: string,
  init: RequestInit = {},
  options: ApiRequestOptions = {},
): Promise<Response> {
  const timeout = createTimeoutSignal(
    options.signal ?? init.signal ?? undefined,
    options.timeoutMs ?? DEFAULT_TIMEOUT_MS,
  );
  try {
    const response = await fetch(apiUrl(path), { ...init, signal: timeout.signal });
    if (!response.ok) {
      throw await responseToError(response);
    }
    return response;
  } catch (error) {
    throw normalizeTransportError(error);
  } finally {
    timeout.cleanup();
  }
}

export async function apiJson<T>(
  path: string,
  init: RequestInit = {},
  options: ApiRequestOptions = {},
): Promise<T> {
  const response = await apiRequest(path, init, options);
  return (await response.json()) as T;
}

export async function uploadImage(
  file: File,
  signal?: AbortSignal,
): Promise<UploadedImage> {
  const body = new FormData();
  body.append("file", file, file.name);
  const timeout = createTimeoutSignal(signal, UPLOAD_TIMEOUT_MS);

  try {
    const response = await fetch(apiUrl("/api/v1/images"), {
      method: "POST",
      body,
      signal: timeout.signal,
    });
    if (!response.ok) {
      throw await responseToError(response);
    }
    return (await response.json()) as UploadedImage;
  } catch (error) {
    throw normalizeTransportError(error);
  } finally {
    timeout.cleanup();
  }
}

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const timeout = createTimeoutSignal(signal, HEALTH_TIMEOUT_MS);
  try {
    const response = await fetch(apiUrl("/api/v1/health"), {
      cache: "no-store",
      signal: timeout.signal,
    });
    if (!response.ok) {
      throw await responseToError(response);
    }
    return (await response.json()) as HealthResponse;
  } catch (error) {
    throw normalizeTransportError(error);
  } finally {
    timeout.cleanup();
  }
}

export async function fetchConfig(signal?: AbortSignal): Promise<RuntimeConfig> {
  const timeout = createTimeoutSignal(signal, CONFIG_TIMEOUT_MS);
  try {
    const response = await fetch(apiUrl("/api/v1/config"), {
      cache: "no-store",
      signal: timeout.signal,
    });
    if (!response.ok) {
      throw await responseToError(response);
    }
    return (await response.json()) as RuntimeConfig;
  } catch (error) {
    throw normalizeTransportError(error);
  } finally {
    timeout.cleanup();
  }
}
