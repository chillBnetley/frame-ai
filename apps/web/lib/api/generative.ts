import { apiJson, apiRequest, apiUrl } from "@/lib/api/client";
import type {
  GenerativeMaskCreate,
  GenerativeMaskListResponse,
  GenerativeMaskView,
} from "@/types/generative";

const JSON_HEADERS = { "Content-Type": "application/json" };
const MASK_TIMEOUT_MS = 30_000;
const PREFIX = "/api/v1/generative";

function maskPath(maskId: string, suffix = ""): string {
  return `${PREFIX}/masks/${encodeURIComponent(maskId)}${suffix}`;
}

export function generativeMaskImageUrl(maskId: string): string {
  return apiUrl(maskPath(maskId, "/image"));
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
