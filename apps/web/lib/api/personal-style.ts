import { apiJson, apiRequest } from "@/lib/api/client";
import type {
  CustomStyleParseRequest,
  CustomStyleParseResponse,
  CustomStyleRefineResponse,
  ImageListResponse,
  PersonalStyleAnalysisResponse,
  PersonalStyleCompareResponse,
  PersonalStyleCreateRequest,
  PersonalStyleDetailResponse,
  PersonalStyleFavoriteResponse,
  PersonalStyleFusionResponse,
  PersonalStyleListResponse,
  PersonalStyleReferenceListResponse,
  PersonalStyleStatus,
  PersonalStyleStatusResponse,
  PersonalStyleUpdateRequest,
  PersonalStyleVersionDetailResponse,
  PersonalStyleVersionListResponse,
  PhotoVisualFeatures,
  StyleAuthoringDraft,
} from "@/types/personal-style";

const LIST_TIMEOUT_MS = 15_000;
const DETAIL_TIMEOUT_MS = 15_000;
const MUTATION_TIMEOUT_MS = 30_000;
const ANALYSIS_TIMEOUT_MS = 30_000;
const FUSION_TIMEOUT_MS = 60_000;
const PREFIX = "/api/v1/personal-styles";

function stylePath(styleId: string): string {
  return `${PREFIX}/${encodeURIComponent(styleId)}`;
}

export interface ImageLibraryQuery {
  limit?: number;
  offset?: number;
}

export async function fetchImageLibrary(
  query: ImageLibraryQuery = {},
  signal?: AbortSignal,
): Promise<ImageListResponse> {
  const params = new URLSearchParams();
  if (query.limit !== undefined) params.set("limit", String(query.limit));
  if (query.offset !== undefined) params.set("offset", String(query.offset));
  const suffix = params.size > 0 ? `?${params.toString()}` : "";
  return apiJson<ImageListResponse>(
    `/api/v1/images${suffix}`,
    { cache: "no-store" },
    { signal, timeoutMs: LIST_TIMEOUT_MS },
  );
}

export async function listPersonalStyles(
  options: { status?: PersonalStyleStatus } = {},
  signal?: AbortSignal,
): Promise<PersonalStyleListResponse> {
  const params = new URLSearchParams();
  if (options.status !== undefined) params.set("status", options.status);
  const suffix = params.size > 0 ? `?${params.toString()}` : "";
  return apiJson<PersonalStyleListResponse>(
    `${PREFIX}${suffix}`,
    { cache: "no-store" },
    { signal, timeoutMs: LIST_TIMEOUT_MS },
  );
}

export async function fetchPersonalStyle(
  styleId: string,
  options: { version?: string; signal?: AbortSignal } = {},
): Promise<PersonalStyleDetailResponse> {
  const params = new URLSearchParams();
  if (options.version !== undefined) params.set("version", options.version);
  const suffix = params.size > 0 ? `?${params.toString()}` : "";
  return apiJson<PersonalStyleDetailResponse>(
    `${stylePath(styleId)}${suffix}`,
    { cache: "no-store" },
    { signal: options.signal, timeoutMs: DETAIL_TIMEOUT_MS },
  );
}

export async function createPersonalStyle(
  payload: PersonalStyleCreateRequest,
  signal?: AbortSignal,
): Promise<PersonalStyleDetailResponse> {
  return apiJson<PersonalStyleDetailResponse>(
    PREFIX,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    },
    { signal, timeoutMs: MUTATION_TIMEOUT_MS },
  );
}

export async function updatePersonalStyle(
  styleId: string,
  payload: PersonalStyleUpdateRequest,
  signal?: AbortSignal,
): Promise<PersonalStyleDetailResponse> {
  return apiJson<PersonalStyleDetailResponse>(
    stylePath(styleId),
    {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    },
    { signal, timeoutMs: MUTATION_TIMEOUT_MS },
  );
}

export async function deletePersonalStyle(
  styleId: string,
  signal?: AbortSignal,
): Promise<void> {
  await apiRequest(
    `${stylePath(styleId)}?confirm=true`,
    { method: "DELETE" },
    { signal, timeoutMs: MUTATION_TIMEOUT_MS },
  );
}

export async function setPersonalStyleStatus(
  styleId: string,
  status: PersonalStyleStatus,
  signal?: AbortSignal,
): Promise<PersonalStyleStatusResponse> {
  return apiJson<PersonalStyleStatusResponse>(
    `${stylePath(styleId)}/status`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ status }),
    },
    { signal, timeoutMs: MUTATION_TIMEOUT_MS },
  );
}

export async function setPersonalStyleFavorite(
  styleId: string,
  favorite: boolean,
  signal?: AbortSignal,
): Promise<PersonalStyleFavoriteResponse> {
  return apiJson<PersonalStyleFavoriteResponse>(
    `${stylePath(styleId)}/favorite`,
    { method: favorite ? "POST" : "DELETE" },
    { signal, timeoutMs: MUTATION_TIMEOUT_MS },
  );
}

export async function addPersonalStyleReferences(
  styleId: string,
  imageIds: string[],
  signal?: AbortSignal,
): Promise<PersonalStyleReferenceListResponse> {
  return apiJson<PersonalStyleReferenceListResponse>(
    `${stylePath(styleId)}/references`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ imageIds, consent: true }),
    },
    { signal, timeoutMs: MUTATION_TIMEOUT_MS },
  );
}

export async function removePersonalStyleReference(
  styleId: string,
  referenceId: string,
  signal?: AbortSignal,
): Promise<void> {
  await apiRequest(
    `${stylePath(styleId)}/references/${encodeURIComponent(referenceId)}`,
    { method: "DELETE" },
    { signal, timeoutMs: MUTATION_TIMEOUT_MS },
  );
}

export async function analyzePersonalStyle(
  styleId: string,
  options: { referenceIds?: string[]; force?: boolean; signal?: AbortSignal } = {},
): Promise<PersonalStyleAnalysisResponse> {
  return apiJson<PersonalStyleAnalysisResponse>(
    `${stylePath(styleId)}/analyze`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        referenceIds: options.referenceIds,
        force: options.force ?? false,
      }),
    },
    { signal: options.signal, timeoutMs: ANALYSIS_TIMEOUT_MS },
  );
}

export async function fetchPersonalStyleAnalysis(
  styleId: string,
  signal?: AbortSignal,
): Promise<PersonalStyleAnalysisResponse> {
  return apiJson<PersonalStyleAnalysisResponse>(
    `${stylePath(styleId)}/analysis`,
    { cache: "no-store" },
    { signal, timeoutMs: ANALYSIS_TIMEOUT_MS },
  );
}

export async function fetchReferenceFeatures(
  styleId: string,
  referenceId: string,
  signal?: AbortSignal,
): Promise<PhotoVisualFeatures> {
  return apiJson<PhotoVisualFeatures>(
    `${stylePath(styleId)}/references/${encodeURIComponent(referenceId)}/features`,
    { cache: "no-store" },
    { signal, timeoutMs: ANALYSIS_TIMEOUT_MS },
  );
}

export async function fusePersonalStyle(
  styleId: string,
  options: { referenceIds?: string[]; note?: string; signal?: AbortSignal } = {},
): Promise<PersonalStyleFusionResponse> {
  return apiJson<PersonalStyleFusionResponse>(
    `${stylePath(styleId)}/fuse`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        referenceIds: options.referenceIds,
        note: options.note,
      }),
    },
    { signal: options.signal, timeoutMs: FUSION_TIMEOUT_MS },
  );
}

export async function fetchPersonalStyleVersions(
  styleId: string,
  signal?: AbortSignal,
): Promise<PersonalStyleVersionListResponse> {
  return apiJson<PersonalStyleVersionListResponse>(
    `${stylePath(styleId)}/versions`,
    { cache: "no-store" },
    { signal, timeoutMs: DETAIL_TIMEOUT_MS },
  );
}

export async function fetchPersonalStyleVersion(
  styleId: string,
  version: string,
  signal?: AbortSignal,
): Promise<PersonalStyleVersionDetailResponse> {
  return apiJson<PersonalStyleVersionDetailResponse>(
    `${stylePath(styleId)}/versions/${encodeURIComponent(version)}`,
    { cache: "no-store" },
    { signal, timeoutMs: DETAIL_TIMEOUT_MS },
  );
}

export async function comparePersonalStyleVersions(
  styleId: string,
  fromVersion: string,
  toVersion: string,
  signal?: AbortSignal,
): Promise<PersonalStyleCompareResponse> {
  const params = new URLSearchParams({ from: fromVersion, to: toVersion });
  return apiJson<PersonalStyleCompareResponse>(
    `${stylePath(styleId)}/compare?${params.toString()}`,
    { cache: "no-store" },
    { signal, timeoutMs: DETAIL_TIMEOUT_MS },
  );
}

export async function parseCustomStyle(
  payload: CustomStyleParseRequest,
  signal?: AbortSignal,
): Promise<CustomStyleParseResponse> {
  return apiJson<CustomStyleParseResponse>(
    `${PREFIX}/custom/parse`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    },
    { signal, timeoutMs: FUSION_TIMEOUT_MS },
  );
}

export async function saveCustomStyle(
  draft: StyleAuthoringDraft,
  options: { note?: string; signal?: AbortSignal } = {},
): Promise<PersonalStyleDetailResponse> {
  return apiJson<PersonalStyleDetailResponse>(
    `${PREFIX}/custom`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ draft, note: options.note }),
    },
    { signal: options.signal, timeoutMs: MUTATION_TIMEOUT_MS },
  );
}

export async function refinePersonalStyle(
  styleId: string,
  instruction: string,
  signal?: AbortSignal,
): Promise<CustomStyleRefineResponse> {
  return apiJson<CustomStyleRefineResponse>(
    `${stylePath(styleId)}/refine`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ instruction }),
    },
    { signal, timeoutMs: FUSION_TIMEOUT_MS },
  );
}

export async function applyPersonalStyleRefinement(
  styleId: string,
  draft: StyleAuthoringDraft,
  options: { note?: string; signal?: AbortSignal } = {},
): Promise<PersonalStyleDetailResponse> {
  return apiJson<PersonalStyleDetailResponse>(
    `${stylePath(styleId)}/refine/apply`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ draft, note: options.note }),
    },
    { signal: options.signal, timeoutMs: MUTATION_TIMEOUT_MS },
  );
}

export async function restorePersonalStyleVersion(
  styleId: string,
  version: string,
  signal?: AbortSignal,
): Promise<PersonalStyleDetailResponse> {
  return apiJson<PersonalStyleDetailResponse>(
    `${stylePath(styleId)}/versions/${encodeURIComponent(version)}/restore`,
    { method: "POST" },
    { signal, timeoutMs: MUTATION_TIMEOUT_MS },
  );
}
