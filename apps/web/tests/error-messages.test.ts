import { describe, expect, it } from "vitest";

import { ApiClientError } from "@/lib/api/client";
import { describeUploadError } from "@/lib/api/errors";
import {
  describeEditorError,
  editorErrorMessage,
  isSilentEditorError,
} from "@/lib/error-messages";

describe("describeUploadError", () => {
  it.each([
    ["payload_too_large", "上传数据超过服务器允许的大小。"],
    ["image_too_many_pixels", "图片像素总数超过允许上限。"],
    ["animated_not_supported", "阶段 1 不支持动图，请换用静态图片。"],
    ["cors_origin_denied", "当前来源不被允许访问 API。"],
    ["invalid_upload", "一次只能上传一张图片。"],
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

describe("describeEditorError", () => {
  it.each([
    ["revision_conflict", "编辑状态已更新，已为你刷新。"],
    ["nothing_to_undo", "没有可撤销的步骤。"],
    ["nothing_to_redo", "没有可重做的步骤。"],
    ["session_not_found", "找不到这张图片或会话，可能已被清理。请重新上传。"],
    ["server_busy", "正在处理另一张高清导出，请稍后几秒再试。"],
    ["network_error", "无法连接后端服务。请确认已启动 API。"],
  ])("maps %s to Chinese copy", (code, expected) => {
    const result = describeEditorError(new ApiClientError(code, "raw server message"));

    expect(result).toEqual({ code, message: expected, details: {} });
  });

  it("names the offending field for validation errors", () => {
    expect(editorErrorMessage("validation_error", { field: "adjustments.crop" })).toBe(
      "有参数超出范围，已恢复到上次有效值（adjustments.crop）。",
    );
  });

  it("keeps preview_expired silent", () => {
    expect(isSilentEditorError("preview_expired")).toBe(true);
    expect(isSilentEditorError("network_error")).toBe(false);
    expect(describeEditorError(new ApiClientError("preview_expired", "expired")).message).toBe(
      "",
    );
  });

  it("wraps unknown failures", () => {
    expect(describeEditorError(new Error("boom"))).toEqual({
      code: "unknown_error",
      message: "boom",
      details: {},
    });
  });
});
