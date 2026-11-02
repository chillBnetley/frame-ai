import { describe, expect, it } from "vitest";

import { ApiClientError } from "@/lib/api/client";
import { describeUploadError } from "@/lib/api/errors";

describe("describeUploadError", () => {
  it.each([
    ["payload_too_large", "上传数据超过服务器允许的大小。"],
    ["image_too_many_pixels", "图片像素总数超过允许上限。"],
    ["animated_not_supported", "阶段 1 不支持动图，请换用静态图片。"],
    ["cors_origin_denied", "当前来源不被允许访问 API。"],
    ["storage_error", "原图保存失败，请稍后重试。"],
    ["internal_error", "服务出现未预期错误，请稍后重试。"],
  ])("maps %s to Chinese copy", (code, expected) => {
    const result = describeUploadError(new ApiClientError(code, "raw server message"));

    expect(result).toEqual({ code, message: expected });
  });

  it("uses the server maxBytes in the size message", () => {
    const result = describeUploadError(
      new ApiClientError("file_too_large", "raw", 413, { maxBytes: 4096 }),
    );

    expect(result.message).toBe("文件超过 4.0 KB 的上传上限。");
  });
});
