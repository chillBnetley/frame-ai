import { apiJson, apiRequest } from "@/lib/api/client";
import type { PersonalStyleDetailResponse } from "@/types/personal-style";
import type {
  StyleEvolutionPreviewResponse,
  StyleFeedbackCreateRequest,
  StyleFeedbackListResponse,
  StyleFeedbackRecord,
  StyleFeedbackScope,
  StyleEvolutionListResponse,
} from "@/types/style-evolution";

const LIST_TIMEOUT_MS = 15_000;
const MUTATION_TIMEOUT_MS = 30_000;
const PREFIX = "/api/v1/personal-styles";

function stylePath(styleId: string): string {
  return `${PREFIX}/${encodeURIComponent(styleId)}`;
}

export async function addStyleFeedback(
  styleId: string,
  payload: StyleFeedbackCreateRequest,
  signal?: AbortSignal,
): Promise<StyleFeedbackRecord> {
  return apiJson<StyleFeedbackRecord>(
    `${stylePath(styleId)}/feedback`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    },
    { signal, timeoutMs: MUTATION_TIMEOUT_MS },
  );
}

export async function listStyleFeedback(
  styleId: string,
  options: { scope?: StyleFeedbackScope; signal?: AbortSignal } = {},
): Promise<StyleFeedbackListResponse> {
  const params = new URLSearchParams();
  if (options.scope !== undefined) params.set("scope", options.scope);
  const suffix = params.size > 0 ? `?${params.toString()}` : "";
  return apiJson<StyleFeedbackListResponse>(
    `${stylePath(styleId)}/feedback${suffix}`,
    { cache: "no-store" },
    { signal: options.signal, timeoutMs: LIST_TIMEOUT_MS },
  );
}

export async function deleteStyleFeedback(
  styleId: string,
  feedbackId: string,
  signal?: AbortSignal,
): Promise<void> {
  await apiRequest(
    `${stylePath(styleId)}/feedback/${encodeURIComponent(feedbackId)}`,
    { method: "DELETE" },
    { signal, timeoutMs: MUTATION_TIMEOUT_MS },
  );
}

export async function previewStyleEvolution(
  styleId: string,
  payload: { feedbackIds?: string[]; note?: string } = {},
  signal?: AbortSignal,
): Promise<StyleEvolutionPreviewResponse> {
  return apiJson<StyleEvolutionPreviewResponse>(
    `${stylePath(styleId)}/evolve/preview`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ feedbackIds: payload.feedbackIds, note: payload.note }),
    },
    { signal, timeoutMs: MUTATION_TIMEOUT_MS },
  );
}

export async function applyStyleEvolution(
  styleId: string,
  evolutionId: string,
  payload: { note?: string } = {},
  signal?: AbortSignal,
): Promise<PersonalStyleDetailResponse> {
  return apiJson<PersonalStyleDetailResponse>(
    `${stylePath(styleId)}/evolve/${encodeURIComponent(evolutionId)}/apply`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ confirm: true, note: payload.note }),
    },
    { signal, timeoutMs: MUTATION_TIMEOUT_MS },
  );
}

export async function discardStyleEvolution(
  styleId: string,
  evolutionId: string,
  signal?: AbortSignal,
): Promise<void> {
  await apiRequest(
    `${stylePath(styleId)}/evolve/${encodeURIComponent(evolutionId)}/discard`,
    { method: "POST" },
    { signal, timeoutMs: MUTATION_TIMEOUT_MS },
  );
}

export async function listStyleEvolutions(
  styleId: string,
  signal?: AbortSignal,
): Promise<StyleEvolutionListResponse> {
  return apiJson<StyleEvolutionListResponse>(
    `${stylePath(styleId)}/evolutions`,
    { cache: "no-store" },
    { signal, timeoutMs: LIST_TIMEOUT_MS },
  );
}
