import { formatBytes } from "@/lib/format";
import type { UploadError } from "@/types/image";

const configuredMaxBytes = Number(process.env.NEXT_PUBLIC_MAX_UPLOAD_BYTES);

export const MAX_UPLOAD_BYTES =
  Number.isFinite(configuredMaxBytes) && configuredMaxBytes > 0
    ? configuredMaxBytes
    : 20 * 1024 * 1024;

export const ACCEPTED_MIME_TYPES = [
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/tiff",
] as const;
export const FILE_ACCEPT_ATTRIBUTE =
  "image/jpeg,image/png,image/webp,image/tiff,.jpg,.jpeg,.jpe,.jfif,.png,.webp,.tif,.tiff";

// Browsers and some Windows shells report .jpg files with these non-standard
// JPEG MIME aliases. They must behave exactly like image/jpeg everywhere.
const MIME_ALIASES: Record<string, string> = {
  "image/jpg": "image/jpeg",
  "image/pjpeg": "image/jpeg",
  "image/x-jpeg": "image/jpeg",
  "image/jfif": "image/jpeg",
};

const MIME_BY_EXTENSION: Record<string, string> = {
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  jpe: "image/jpeg",
  jfif: "image/jpeg",
  png: "image/png",
  webp: "image/webp",
  tif: "image/tiff",
  tiff: "image/tiff",
};

const GENERIC_MIME_TYPES = new Set(["", "application/octet-stream"]);

export function resolveUploadMimeType(file: File): string {
  const declared = file.type.trim().toLowerCase();
  if (!GENERIC_MIME_TYPES.has(declared)) {
    return MIME_ALIASES[declared] ?? declared;
  }
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  return MIME_BY_EXTENSION[extension] ?? declared;
}

/**
 * Rebuilds the file with a canonical MIME type so the multipart part carries
 * a type the API accepts. Untouched files are returned as-is.
 */
export function normalizeUploadFile(file: File): File {
  const mimeType = resolveUploadMimeType(file);
  if (!mimeType || mimeType === file.type) {
    return file;
  }
  return new File([file], file.name, { type: mimeType, lastModified: file.lastModified });
}

export interface UploadLimits {
  maxUploadBytes: number;
  allowedMimeTypes: readonly string[];
}

export const DEFAULT_UPLOAD_LIMITS: UploadLimits = {
  maxUploadBytes: MAX_UPLOAD_BYTES,
  allowedMimeTypes: ACCEPTED_MIME_TYPES,
};

export type UploadValidation = { ok: true } | ({ ok: false } & UploadError);

export function validateUploadFile(
  file: File,
  limits: UploadLimits = DEFAULT_UPLOAD_LIMITS,
): UploadValidation {
  if (file.size <= 0) {
    return { ok: false, code: "empty_file", message: "文件为空，请重新选择。" };
  }
  if (file.size > limits.maxUploadBytes) {
    return {
      ok: false,
      code: "file_too_large",
      message: `文件超过 ${formatBytes(limits.maxUploadBytes)} 的上传上限。`,
    };
  }
  const mimeType = resolveUploadMimeType(file);
  if (mimeType && !limits.allowedMimeTypes.includes(mimeType)) {
    return {
      ok: false,
      code: "unsupported_media_type",
      message: "仅支持 JPG/JPEG、PNG、WebP 与 TIFF 图片。",
    };
  }
  return { ok: true };
}
