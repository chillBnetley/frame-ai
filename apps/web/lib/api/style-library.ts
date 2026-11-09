import { apiJson, apiRequest } from "@/lib/api/client";
import type {
  ConversionModeListResponse,
  SceneLabel,
  StyleDetailResponse,
  StyleFitResponse,
  StyleKind,
  StyleLibraryListResponse,
  StyleRecentResponse,
  StyleRecommendedResponse,
} from "@/types/style-library";

const LIST_TIMEOUT_MS = 15_000;
const FIT_TIMEOUT_MS = 30_000;
const DETAIL_TIMEOUT_MS = 15_000;

export interface StyleLibraryQuery {
  kind?: StyleKind;
  scene?: SceneLabel;
  search?: string;
  includeDisabled?: boolean;
}

function styleQuery(query: StyleLibraryQuery): string {
  const params = new URLSearchParams();
  if (query.kind !== undefined) params.set("kind", query.kind);
  if (query.scene !== undefined) params.set("scene", query.scene);
  if (query.search !== undefined && query.search.trim() !== "") {
    params.set("search", query.search.trim());
  }
  if (query.includeDisabled) params.set("include_disabled", "true");
  return params.size > 0 ? `?${params.toString()}` : "";
}

export async function fetchStyleLibrary(
  query: StyleLibraryQuery = {},
  signal?: AbortSignal,
): Promise<StyleLibraryListResponse> {
  return apiJson<StyleLibraryListResponse>(
    `/api/v1/styles${styleQuery(query)}`,
    { cache: "no-store" },
    { signal, timeoutMs: LIST_TIMEOUT_MS },
  );
}

export async function fetchStyleDetail(
  styleId: string,
  signal?: AbortSignal,
): Promise<StyleDetailResponse> {
  return apiJson<StyleDetailResponse>(
    `/api/v1/styles/${encodeURIComponent(styleId)}`,
    { cache: "no-store" },
    { signal, timeoutMs: DETAIL_TIMEOUT_MS },
  );
}

export async function fetchFavorites(
  signal?: AbortSignal,
): Promise<StyleLibraryListResponse> {
  return apiJson<StyleLibraryListResponse>(
    "/api/v1/styles/favorites",
    { cache: "no-store" },
    { signal, timeoutMs: LIST_TIMEOUT_MS },
  );
}

export async function fetchRecent(
  limit = 8,
  signal?: AbortSignal,
): Promise<StyleRecentResponse> {
  return apiJson<StyleRecentResponse>(
    `/api/v1/styles/recent?limit=${limit}`,
    { cache: "no-store" },
    { signal, timeoutMs: LIST_TIMEOUT_MS },
  );
}

export async function fetchRecommended(
  options: { imageId?: string; limit?: number } = {},
  signal?: AbortSignal,
): Promise<StyleRecommendedResponse> {
  const params = new URLSearchParams({ limit: String(options.limit ?? 6) });
  if (options.imageId) params.set("image_id", options.imageId);
  return apiJson<StyleRecommendedResponse>(
    `/api/v1/styles/recommended?${params.toString()}`,
    { cache: "no-store" },
    { signal, timeoutMs: LIST_TIMEOUT_MS },
  );
}

export async function fetchStyleFit(
  styleId: string,
  imageId: string,
  signal?: AbortSignal,
  alternatives = 3,
): Promise<StyleFitResponse> {
  const params = new URLSearchParams({
    image_id: imageId,
    alternatives: String(alternatives),
  });
  return apiJson<StyleFitResponse>(
    `/api/v1/styles/${encodeURIComponent(styleId)}/fit?${params.toString()}`,
    { cache: "no-store" },
    { signal, timeoutMs: FIT_TIMEOUT_MS },
  );
}

export async function setStyleFavorite(
  styleId: string,
  favorite: boolean,
  signal?: AbortSignal,
): Promise<{ styleId: string; favorite: boolean }> {
  if (favorite) {
    return apiJson<{ styleId: string; favorite: boolean }>(
      `/api/v1/styles/${encodeURIComponent(styleId)}/favorite`,
      { method: "POST" },
      { signal },
    );
  }
  return apiJson<{ styleId: string; favorite: boolean }>(
    `/api/v1/styles/${encodeURIComponent(styleId)}/favorite`,
    { method: "DELETE" },
    { signal },
  );
}

export async function fetchConversionModes(
  signal?: AbortSignal,
): Promise<ConversionModeListResponse> {
  return apiJson<ConversionModeListResponse>(
    "/api/v1/ai/photographer/conversion-modes",
    { cache: "no-store" },
    { signal, timeoutMs: LIST_TIMEOUT_MS },
  );
}

export async function setStyleEnabled(
  styleId: string,
  enabled: boolean,
  signal?: AbortSignal,
): Promise<void> {
  await apiRequest(
    `/api/v1/styles/${encodeURIComponent(styleId)}/enabled`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    },
    { signal, timeoutMs: LIST_TIMEOUT_MS },
  );
}
