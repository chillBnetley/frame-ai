import type {
  AnalysisReport,
  AnalysisStatusResponse,
  AnalysisTaskCreated,
} from "@/types/analysis";

import { apiJson, apiRequest, type ApiRequestOptions } from "./client";

export async function createAnalysis(
  imageId: string,
  options: { force?: boolean; signal?: AbortSignal } = {},
): Promise<AnalysisTaskCreated> {
  return apiJson<AnalysisTaskCreated>(
    "/api/v1/analysis",
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ imageId, force: options.force ?? false }),
    },
    { signal: options.signal },
  );
}

export async function fetchAnalysisStatus(
  analysisId: string,
  signal?: AbortSignal,
): Promise<AnalysisStatusResponse> {
  return apiJson<AnalysisStatusResponse>(
    `/api/v1/analysis/${encodeURIComponent(analysisId)}`,
    { cache: "no-store" },
    { signal },
  );
}

export async function fetchAnalysisReport(
  analysisId: string,
  signal?: AbortSignal,
): Promise<AnalysisReport> {
  return apiJson<AnalysisReport>(
    `/api/v1/analysis/${encodeURIComponent(analysisId)}/result`,
    { cache: "no-store" },
    { signal },
  );
}

export async function deleteAnalysis(
  analysisId: string,
  options: ApiRequestOptions = {},
): Promise<void> {
  await apiRequest(
    `/api/v1/analysis/${encodeURIComponent(analysisId)}`,
    { method: "DELETE" },
    options,
  );
}