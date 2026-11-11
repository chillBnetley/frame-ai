import type { components } from "./api";

export type UploadedImage = components["schemas"]["UploadImageResponse"];
export type ImageDeletionPreview = components["schemas"]["ImageDeletionPreviewResponse"];
export type ApiErrorBody = components["schemas"]["ErrorResponse"];
export type HealthResponse = components["schemas"]["HealthResponse"];
export type RuntimeConfig = components["schemas"]["RuntimeConfigResponse"];

export type ApiStatus = "checking" | "online" | "offline";

export interface UploadError {
  code: string;
  message: string;
  requestId?: string | null;
}
