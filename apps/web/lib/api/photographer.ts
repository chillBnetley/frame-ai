import { apiJson, apiRequest } from "@/lib/api/client";
import type { SessionState } from "@/types/session";
import type {
  AcceptPlanRequest,
  CritiqueApplyRequest,
  CritiqueApplyResponse,
  FeedbackListResponse,
  PhotographerCritique,
  PhotographerCritiqueRequest,
  PhotographerFeedback,
  PhotographerFeedbackRequest,
  PhotographerPatchRequest,
  PhotographerPatchResponse,
  PhotographerPlanRequest,
  PhotographerPlanResponse,
  StyleListResponse,
} from "@/types/photographer";

const PLANNER_TIMEOUT_MS = 120_000;

export async function fetchStyles(
  signal?: AbortSignal,
): Promise<StyleListResponse> {
  return apiJson<StyleListResponse>(
    "/api/v1/ai/photographer/styles",
    { cache: "no-store" },
    { signal },
  );
}

export async function createPlan(
  request: PhotographerPlanRequest,
  signal?: AbortSignal,
): Promise<PhotographerPlanResponse> {
  return apiJson<PhotographerPlanResponse>(
    "/api/v1/ai/photographer/plan",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    { signal, timeoutMs: PLANNER_TIMEOUT_MS },
  );
}

export async function acceptPlan(
  planId: string,
  request: AcceptPlanRequest,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<SessionState> {
  return apiJson<SessionState>(
    `/api/v1/ai/photographer/plan/${encodeURIComponent(planId)}/accept`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
      },
      body: JSON.stringify(request),
    },
    { signal, timeoutMs: PLANNER_TIMEOUT_MS },
  );
}

export async function sendChat(
  request: PhotographerPatchRequest,
  signal?: AbortSignal,
): Promise<PhotographerPatchResponse> {
  return apiJson<PhotographerPatchResponse>(
    "/api/v1/ai/photographer/chat",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    { signal, timeoutMs: PLANNER_TIMEOUT_MS },
  );
}

export async function fetchCritique(
  request: PhotographerCritiqueRequest,
  signal?: AbortSignal,
): Promise<PhotographerCritique> {
  return apiJson<PhotographerCritique>(
    "/api/v1/ai/photographer/critique",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    { signal },
  );
}

export async function applyCritique(
  request: CritiqueApplyRequest,
  signal?: AbortSignal,
): Promise<CritiqueApplyResponse> {
  return apiJson<CritiqueApplyResponse>(
    "/api/v1/ai/photographer/critique/apply",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    { signal },
  );
}

export async function recordFeedback(
  request: PhotographerFeedbackRequest,
  signal?: AbortSignal,
): Promise<PhotographerFeedback> {
  return apiJson<PhotographerFeedback>(
    "/api/v1/ai/photographer/feedback",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    { signal },
  );
}

export async function fetchFeedback(
  filter: {
    sessionId?: string;
    imageId?: string;
    planId?: string;
    limit?: number;
  } = {},
  signal?: AbortSignal,
): Promise<FeedbackListResponse> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filter)) {
    if (value !== undefined && value !== null) {
      params.set(key, String(value));
    }
  }
  const query = params.size > 0 ? `?${params.toString()}` : "";
  return apiJson<FeedbackListResponse>(
    `/api/v1/ai/photographer/feedback${query}`,
    { cache: "no-store" },
    { signal },
  );
}

export async function deleteFeedback(
  feedbackId: string,
  signal?: AbortSignal,
): Promise<void> {
  await apiRequest(
    `/api/v1/ai/photographer/feedback/${encodeURIComponent(feedbackId)}`,
    { method: "DELETE" },
    { signal },
  );
}
