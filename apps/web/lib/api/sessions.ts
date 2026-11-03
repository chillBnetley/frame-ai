import { apiJson, apiRequest } from "@/lib/api/client";
import type {
  CompareResponse,
  EditRecipe,
  ExportFormat,
  RenderResponse,
  RevisionListResponse,
  SessionState,
} from "@/types/session";

const JSON_HEADERS = { "Content-Type": "application/json" };
const SESSION_TIMEOUT_MS = 15_000;
const RENDER_TIMEOUT_MS = 60_000;
const REVISION_TIMEOUT_MS = 30_000;
const EXPORT_TIMEOUT_MS = 120_000;

function sessionPath(sessionId: string, suffix = ""): string {
  return `/api/v1/sessions/${encodeURIComponent(sessionId)}${suffix}`;
}

export async function createSession(
  imageId: string,
  signal?: AbortSignal,
): Promise<SessionState> {
  return apiJson<SessionState>(
    "/api/v1/sessions",
    {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ imageId }),
    },
    { signal, timeoutMs: SESSION_TIMEOUT_MS },
  );
}

export async function getSession(
  sessionId: string,
  signal?: AbortSignal,
): Promise<SessionState> {
  return apiJson<SessionState>(
    sessionPath(sessionId),
    { cache: "no-store" },
    { signal, timeoutMs: SESSION_TIMEOUT_MS },
  );
}

export async function listRevisions(
  sessionId: string,
  options: { limit?: number; cursor?: number | null } = {},
  signal?: AbortSignal,
): Promise<RevisionListResponse> {
  const params = new URLSearchParams();
  if (options.limit !== undefined) {
    params.set("limit", String(options.limit));
  }
  if (options.cursor !== undefined && options.cursor !== null) {
    params.set("cursor", String(options.cursor));
  }
  const query = params.size > 0 ? `?${params.toString()}` : "";
  return apiJson<RevisionListResponse>(
    sessionPath(sessionId, `/revisions${query}`),
    { cache: "no-store" },
    { signal, timeoutMs: SESSION_TIMEOUT_MS },
  );
}

export async function renderPreview(
  sessionId: string,
  request: { recipe: EditRecipe; quality: "draft" | "final"; maxEdge?: number },
  signal?: AbortSignal,
  renderSeq: number = Date.now(),
): Promise<RenderResponse> {
  return apiJson<RenderResponse>(
    sessionPath(sessionId, "/render"),
    {
      method: "POST",
      headers: { ...JSON_HEADERS, "X-Render-Seq": String(renderSeq) },
      body: JSON.stringify({
        recipe: request.recipe,
        quality: request.quality,
        ...(request.maxEdge === undefined ? {} : { maxEdge: request.maxEdge }),
      }),
    },
    { signal, timeoutMs: RENDER_TIMEOUT_MS },
  );
}

export interface CreateRevisionResult {
  state: SessionState;
  replayed: boolean;
}

export async function createRevision(
  sessionId: string,
  request: { recipe: EditRecipe; parentRevisionId: string; source?: "user" | "ai" },
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<CreateRevisionResult> {
  const response = await apiRequest(
    sessionPath(sessionId, "/revisions"),
    {
      method: "POST",
      headers: { ...JSON_HEADERS, "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ ...request, source: request.source ?? "user" }),
    },
    { signal, timeoutMs: REVISION_TIMEOUT_MS },
  );
  return {
    state: (await response.json()) as SessionState,
    replayed: response.status === 200,
  };
}

export async function undoSession(
  sessionId: string,
  revisionId?: string | null,
  signal?: AbortSignal,
): Promise<SessionState> {
  return apiJson<SessionState>(
    sessionPath(sessionId, "/undo"),
    {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(revisionId ? { revisionId } : {}),
    },
    { signal, timeoutMs: SESSION_TIMEOUT_MS },
  );
}

export async function redoSession(
  sessionId: string,
  signal?: AbortSignal,
): Promise<SessionState> {
  return apiJson<SessionState>(
    sessionPath(sessionId, "/redo"),
    { method: "POST" },
    { signal, timeoutMs: SESSION_TIMEOUT_MS },
  );
}

export async function activateRevision(
  sessionId: string,
  revisionId: string,
  signal?: AbortSignal,
): Promise<SessionState> {
  return apiJson<SessionState>(
    sessionPath(sessionId, "/activate"),
    {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ revisionId }),
    },
    { signal, timeoutMs: SESSION_TIMEOUT_MS },
  );
}

export async function resetSession(
  sessionId: string,
  signal?: AbortSignal,
): Promise<SessionState> {
  return apiJson<SessionState>(
    sessionPath(sessionId, "/reset"),
    { method: "POST" },
    { signal, timeoutMs: SESSION_TIMEOUT_MS },
  );
}

export async function compareSession(
  sessionId: string,
  options: { revisionId?: string | null; maxEdge?: number } = {},
  signal?: AbortSignal,
): Promise<CompareResponse> {
  const params = new URLSearchParams();
  if (options.revisionId) {
    params.set("revisionId", options.revisionId);
  }
  if (options.maxEdge !== undefined) {
    params.set("maxEdge", String(options.maxEdge));
  }
  const query = params.size > 0 ? `?${params.toString()}` : "";
  return apiJson<CompareResponse>(
    sessionPath(sessionId, `/compare${query}`),
    { cache: "no-store" },
    { signal, timeoutMs: RENDER_TIMEOUT_MS },
  );
}

export interface ExportResult {
  blob: Blob;
  filename: string;
  width: number | null;
  height: number | null;
  warnings: string[];
}

function parseWarnings(value: string | null): string[] {
  if (!value) {
    return [];
  }
  return value
    .split(",")
    .map((warning) => warning.trim())
    .filter((warning) => warning.length > 0);
}

function parseFilename(disposition: string | null, format: ExportFormat): string {
  const match = /filename="([^"]+)"/i.exec(disposition ?? "");
  if (match?.[1]) {
    return match[1];
  }
  return format === "png" ? "frame.png" : "frame.jpg";
}

function parseDimension(value: string | null): number | null {
  if (!value) {
    return null;
  }
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

export async function exportSession(
  sessionId: string,
  request: { revisionId: string; format: ExportFormat; quality?: number | null },
  signal?: AbortSignal,
): Promise<ExportResult> {
  const response = await apiRequest(
    sessionPath(sessionId, "/export"),
    {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({
        revisionId: request.revisionId,
        format: request.format,
        ...(request.quality === undefined || request.quality === null
          ? {}
          : { quality: request.quality }),
      }),
    },
    { signal, timeoutMs: EXPORT_TIMEOUT_MS },
  );
  return {
    blob: await response.blob(),
    filename: parseFilename(response.headers.get("content-disposition"), request.format),
    width: parseDimension(response.headers.get("x-export-width")),
    height: parseDimension(response.headers.get("x-export-height")),
    warnings: parseWarnings(response.headers.get("x-export-warning")),
  };
}

export function createIdempotencyKey(): string {
  if (typeof globalThis.crypto !== "undefined" && typeof globalThis.crypto.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `${Date.now().toString(16)}-${Math.random().toString(16).slice(2, 10)}`;
}
