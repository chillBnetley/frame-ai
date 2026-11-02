export interface UploadedImage {
  imageId: string;
  originalName: string;
  width: number;
  height: number;
  exifOrientation: number;
  mimeType: string;
  bytes: number;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
}

export interface HealthResponse {
  status: "ok";
  service: string;
  version: string;
  storage: {
    ok: boolean;
    writable: boolean;
  };
}

export interface RuntimeConfig {
  maxUploadBytes: number;
  maxImagePixels: number;
  allowedMimeTypes: string[];
}

export type ApiStatus = "checking" | "online" | "offline";

export interface UploadError {
  code: string;
  message: string;
}
