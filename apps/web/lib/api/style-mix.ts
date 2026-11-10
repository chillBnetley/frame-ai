import { apiJson } from "@/lib/api/client";
import type { PersonalStyleDetailResponse } from "@/types/personal-style";
import type {
  StyleMixPreviewResponse,
  StyleMixRequest,
  StyleMixSaveRequest,
} from "@/types/style-mix";

const PREVIEW_TIMEOUT_MS = 30_000;
const SAVE_TIMEOUT_MS = 30_000;
const PREFIX = "/api/v1/style-mixes";

export async function previewStyleMix(
  payload: StyleMixRequest,
  signal?: AbortSignal,
): Promise<StyleMixPreviewResponse> {
  return apiJson<StyleMixPreviewResponse>(
    `${PREFIX}/preview`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    },
    { signal, timeoutMs: PREVIEW_TIMEOUT_MS },
  );
}

export async function saveStyleMix(
  payload: StyleMixSaveRequest,
  signal?: AbortSignal,
): Promise<PersonalStyleDetailResponse> {
  return apiJson<PersonalStyleDetailResponse>(
    PREFIX,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    },
    { signal, timeoutMs: SAVE_TIMEOUT_MS },
  );
}