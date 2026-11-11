import { apiJson, apiRequest, apiUrl } from "@/lib/api/client";
import type {
  GenerativeCapabilitiesResponse,
  GenerativeMaskCreate,
  GenerativeMaskListResponse,
  GenerativeMaskView,
  GenerativeResultView,
  GenerativeStorageResponse,
  GenerativeTaskCreated,
  GenerativeTaskRequest,
  GenerativeTaskStatusResponse,
} from "@/types/generative";
import type { SessionState } from "@/types/session";

const JSON_HEADERS = { "Content-Type": "application/json" };
const MASK_TIMEOUT_MS = 30_000;
const TASK_TIMEOUT_MS = 30_000;
const PREFIX = "/api/v1/generative";

function maskPath(maskId: string, suffix = ""): string {
  return `${PREFIX}/masks/${encodeURIComponent(maskId)}${suffix}`;
}

function taskPath(taskId: string, suffix = ""): string {
  return `${PREFIX}/tasks/${encodeURIComponent(taskId)}${suffix}`;
}

function resultPath(resultId: string, suffix = ""): string {
  return `${PREFIX}/results/${encodeURIComponent(resultId)}${suffix}`;
}

export function generativeMaskImageUrl(maskId: string): string {
  return apiUrl(maskPath(maskId, "/image"));
}

export function generativeResultImageUrl(resultId: string): string {
  return apiUrl(resultPath(resultId, "/image"));
}

export async function createGenerativeMask(
  payload: GenerativeMaskCreate,
  signal?: AbortSignal,
): Promise<GenerativeMaskView> {
  return apiJson<GenerativeMaskView>(
    `${PREFIX}/masks`,
    {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(payload),
    },
    { signal, timeoutMs: MASK_TIMEOUT_MS },
  );
}

export async function listGenerativeMasks(
  sessionId: string,
  options: { limit?: number; offset?: number } = {},
  signal?: AbortSignal,
): Promise<GenerativeMaskListResponse> {
  const params = new URLSearchParams({ sessionId });
  if (options.limit !== undefined) {
    params.set("limit", String(options.limit));
  }
  if (options.offset !== undefined) {
    params.set("offset", String(options.offset));
  }
  return apiJson<GenerativeMaskListResponse>(
    `${PREFIX}/masks?${params.toString()}`,
    { cache: "no-store" },
    { signal, timeoutMs: MASK_TIMEOUT_MS },
  );
}

export async function getGenerativeMask(
  maskId: string,
  signal?: AbortSignal,
): Promise<GenerativeMaskView> {
  return apiJson<GenerativeMaskView>(
    maskPath(maskId),
    { cache: "no-store" },
    { signal, timeoutMs: MASK_TIMEOUT_MS },
  );
}

export async function deleteGenerativeMask(
  maskId: string,
  signal?: AbortSignal,
): Promise<void> {
  await apiRequest(
    maskPath(maskId),
    { method: "DELETE" },
    { signal, timeoutMs: MASK_TIMEOUT_MS },
  );
}

export async function getGenerativeCapabilities(
  signal?: AbortSignal,
): Promise<GenerativeCapabilitiesResponse> {
  return apiJson<GenerativeCapabilitiesResponse>(
    `${PREFIX}/capabilities`,
    { cache: "no-store" },
    { signal, timeoutMs: TASK_TIMEOUT_MS },
  );
}

export async function getGenerativeStorage(
  signal?: AbortSignal,
): Promise<GenerativeStorageResponse> {
  return apiJson<GenerativeStorageResponse>(
    `${PREFIX}/storage`,
    { cache: "no-store" },
    { signal, timeoutMs: TASK_TIMEOUT_MS },
  );
}

export async function createGenerativeTask(
  payload: GenerativeTaskRequest,
  idempotencyKey?: string,
  signal?: AbortSignal,
): Promise<GenerativeTaskCreated> {
  const headers: Record<string, string> = { ...JSON_HEADERS };
  if (idempotencyKey) {
    headers["Idempotency-Key"] = idempotencyKey;
  }
  return apiJson<GenerativeTaskCreated>(
    `${PREFIX}/tasks`,
    {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    },
    { signal, timeoutMs: TASK_TIMEOUT_MS },
  );
}

export async function getGenerativeTask(
  taskId: string,
  signal?: AbortSignal,
): Promise<GenerativeTaskStatusResponse> {
  return apiJson<GenerativeTaskStatusResponse>(
    taskPath(taskId),
    { cache: "no-store" },
    { signal, timeoutMs: TASK_TIMEOUT_MS },
  );
}

export async function cancelGenerativeTask(
  taskId: string,
  signal?: AbortSignal,
): Promise<GenerativeTaskStatusResponse> {
  return apiJson<GenerativeTaskStatusResponse>(
    taskPath(taskId, "/cancel"),
    {
      method: "POST",
      headers: JSON_HEADERS,
    },
    { signal, timeoutMs: TASK_TIMEOUT_MS },
  );
}

export async function retryGenerativeTask(
  taskId: string,
  signal?: AbortSignal,
): Promise<GenerativeTaskStatusResponse> {
  return apiJson<GenerativeTaskStatusResponse>(
    taskPath(taskId, "/retry"),
    {
      method: "POST",
      headers: JSON_HEADERS,
    },
    { signal, timeoutMs: TASK_TIMEOUT_MS },
  );
}

export async function acceptGenerativeResult(
  resultId: string,
  signal?: AbortSignal,
): Promise<SessionState> {
  return apiJson<SessionState>(
    resultPath(resultId, "/accept"),
    {
      method: "POST",
      headers: JSON_HEADERS,
    },
    { signal, timeoutMs: TASK_TIMEOUT_MS },
  );
}

export async function rejectGenerativeResult(
  resultId: string,
  signal?: AbortSignal,
): Promise<GenerativeResultView> {
  return apiJson<GenerativeResultView>(
    resultPath(resultId, "/reject"),
    {
      method: "POST",
      headers: JSON_HEADERS,
    },
    { signal, timeoutMs: TASK_TIMEOUT_MS },
  );
}

export async function pollGenerativeTask(
  taskId: string,
  options: {
    intervalMs?: number;
    timeoutMs?: number;
    onUpdate?: (task: GenerativeTaskStatusResponse) => void;
  } = {},
  signal?: AbortSignal,
): Promise<GenerativeTaskStatusResponse> {
  const interval = options.intervalMs ?? 500;
  const timeout = options.timeoutMs ?? 300_000;
  const start = Date.now();

  while (true) {
    if (signal?.aborted) {
      throw new DOMException("Generative task polling was aborted", "AbortError");
    }
    const task = await getGenerativeTask(taskId, signal);
    options.onUpdate?.(task);

    if (
      task.status === "succeeded" ||
      task.status === "failed" ||
      task.status === "cancelled" ||
      task.status === "expired"
    ) {
      return task;
    }

    if (Date.now() - start > timeout) {
      throw new Error("Generative task timed out while waiting for completion.");
    }

    await new Promise((resolve) => setTimeout(resolve, interval));
  }
}
