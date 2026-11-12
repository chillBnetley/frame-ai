import { ApiClientError } from "@/lib/api/client";
import { formatBytes } from "@/lib/format";
import type { UploadError } from "@/types/image";

const FRIENDLY_MESSAGES: Record<string, string> = {
  file_too_large: "文件超过上传大小限制。",
  payload_too_large: "上传数据超过服务器允许的大小。",
  image_too_many_pixels: "图片像素总数超过允许上限。",
  animated_not_supported: "阶段 1 不支持动图，请换用静态图片。",
  unsupported_media_type: "仅支持 JPG/JPEG、PNG、WebP 与 TIFF 图片。",
  mime_mismatch: "文件内容与声明的图片类型不一致，已拒绝上传。",
  invalid_image: "文件不是有效图片，或图片已损坏。",
  unsupported_tiff_compression: "这个 TIFF 使用了不支持的压缩方式，请改用未压缩或 Deflate 压缩的单页 TIFF。",
  tiff_multipage_not_supported: "不支持多页 TIFF，请导出为单页后重试。",
  associated_alpha_not_supported: "这个 TIFF 使用预乘 alpha（associated alpha），暂不支持；请导出为非预乘（unassociated）alpha 后重试。",
  unsupported_icc_profile: "16-bit 图片内嵌的 ICC 配置暂不支持（仅支持矩阵/TRC 型），请转换为 sRGB 后重试。",
  empty_file: "文件为空，请重新选择。",
  image_not_found: "找不到这张图片。",
  image_file_missing: "原图文件不可用，可能已被移动或删除。",
  request_timeout: "请求超时，请检查网络或稍后重试。",
  network_error: "无法连接 API 服务，请确认后端已经启动。",
  validation_error: "请求参数不完整，请重新选择文件。",
  invalid_upload: "一次只能上传一张图片。",
  bad_request: "请求无法处理，请重新选择文件。",
  not_found: "请求的资源不存在。",
  method_not_allowed: "请求方式不被支持。",
  cors_origin_denied: "当前来源不被允许访问 API。",
  rate_limited: "请求过于频繁，请稍后重试。",
  service_unavailable: "服务尚未就绪，请稍后重试。",
  provider_unavailable: "外部服务暂不可用，请稍后重试。",
  storage_error: "原图保存失败，请稍后重试。",
  storage_conflict: "原图写入冲突，请重试。",
  internal_error: "服务出现未预期错误，请稍后重试。",
  http_error: "请求失败，请稍后重试。",
};

export function describeUploadError(error: unknown): UploadError {
  if (error instanceof ApiClientError) {
    let message = FRIENDLY_MESSAGES[error.code] ?? error.message;
    if (error.code === "file_too_large" && typeof error.details.maxBytes === "number") {
      message = `文件超过 ${formatBytes(error.details.maxBytes)} 的上传上限。`;
    }
    return error.requestId
      ? { code: error.code, message, requestId: error.requestId }
      : { code: error.code, message };
  }
  if (error instanceof Error) {
    return { code: "unknown_error", message: error.message };
  }
  return { code: "unknown_error", message: "上传失败，请稍后重试。" };
}
