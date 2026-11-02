import { ApiClientError } from "@/lib/api/client";
import { formatBytes } from "@/lib/format";
import type { UploadError } from "@/types/image";

const FRIENDLY_MESSAGES: Record<string, string> = {
  file_too_large: "文件超过上传大小限制。",
  image_pixels_exceeded: "图片像素尺寸超过允许上限。",
  unsupported_media_type: "仅支持 JPEG、PNG 与 WebP 图片。",
  mime_mismatch: "文件内容与声明的图片类型不一致，已拒绝上传。",
  invalid_image: "文件不是有效图片，或图片已损坏。",
  empty_file: "文件为空，请重新选择。",
  image_not_found: "找不到这张图片。",
  image_file_missing: "原图文件不可用，可能已被移动或删除。",
  request_timeout: "请求超时，请检查网络或稍后重试。",
  network_error: "无法连接 API 服务，请确认后端已经启动。",
  validation_error: "请求参数不完整，请重新选择文件。",
  storage_error: "原图保存失败，请稍后重试。",
  internal_error: "服务出现未预期错误，请稍后重试。",
};

export function describeUploadError(error: unknown): UploadError {
  if (error instanceof ApiClientError) {
    let message = FRIENDLY_MESSAGES[error.code] ?? error.message;
    if (error.code === "file_too_large" && typeof error.details.maxBytes === "number") {
      message = `文件超过 ${formatBytes(error.details.maxBytes)} 的上传上限。`;
    }
    return { code: error.code, message };
  }
  if (error instanceof Error) {
    return { code: "unknown_error", message: error.message };
  }
  return { code: "unknown_error", message: "上传失败，请稍后重试。" };
}
