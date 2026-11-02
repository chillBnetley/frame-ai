import { formatBytes } from "@/lib/format";
import type { UploadError } from "@/types/image";

const configuredMaxBytes = Number(process.env.NEXT_PUBLIC_MAX_UPLOAD_BYTES);

export const MAX_UPLOAD_BYTES =
  Number.isFinite(configuredMaxBytes) && configuredMaxBytes > 0
    ? configuredMaxBytes
    : 20 * 1024 * 1024;

export const ACCEPTED_MIME_TYPES = ["image/jpeg", "image/png", "image/webp"] as const;
export const FILE_ACCEPT_ATTRIBUTE = "image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp";

export type UploadValidation = { ok: true } | ({ ok: false } & UploadError);

export function validateUploadFile(file: File): UploadValidation {
  if (file.size <= 0) {
    return { ok: false, code: "empty_file", message: "文件为空，请重新选择。" };
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return {
      ok: false,
      code: "file_too_large",
      message: `文件超过 ${formatBytes(MAX_UPLOAD_BYTES)} 的上传上限。`,
    };
  }
  const mimeType = file.type.toLowerCase();
  if (mimeType && !ACCEPTED_MIME_TYPES.includes(mimeType as (typeof ACCEPTED_MIME_TYPES)[number])) {
    return {
      ok: false,
      code: "unsupported_media_type",
      message: "仅支持 JPEG、PNG 与 WebP 图片。",
    };
  }
  return { ok: true };
}
