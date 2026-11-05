import { describe, expect, it } from "vitest";

import { ApiClientError } from "@/lib/api/client";
import { describeUploadError } from "@/lib/api/errors";
import {
  describeEditorError,
  editorErrorMessage,
  isSilentEditorError,
  validationFields,
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
    ["idempotency_key_reuse", "保存请求与已有版本冲突，请重试。"],
    ["nothing_to_undo", "没有可撤销的步骤。"],
    ["nothing_to_redo", "没有可重做的步骤。"],
    ["session_not_found", "找不到这张图片或会话，可能已被清理。请重新上传。"],
    ["server_busy", "服务器内存不足或正在处理另一张高清导出，请稍后几秒再试。"],
    ["network_error", "无法连接后端服务。请确认已启动 API。"],
    ["not_found", "服务接口不存在，可能是后端版本过旧。请重启 API 后重试。"],
  ])("maps %s to Chinese copy", (code, expected) => {
    const result = describeEditorError(new ApiClientError(code, "raw server message"));

    expect(result).toEqual({ code, message: expected, details: {} });
  });

  it("explains export memory estimates with the configured limit", () => {
    expect(
      editorErrorMessage("export_too_large", { estimatedPeakMb: 5643, limitMb: 3072 }),
    ).toBe(
      "这张图在当前调整下导出需要约 5643 MB 内存，超过上限 3072 MB。可以减少调整项、选择更小的导出长边，或调高 FRAME_EXPORT_MAX_RSS_MB。",
    );
    expect(editorErrorMessage("export_too_large")).toBe(
      "这张图在当前调整下导出所需内存超过上限。可以减少调整项、选择更小的导出长边，或调高 FRAME_EXPORT_MAX_RSS_MB。",
    );
  });

  it("names the offending field for validation errors", () => {
    expect(editorErrorMessage("validation_error", { field: "adjustments.crop" })).toBe(
      "有参数超出范围，已恢复到上次有效值（adjustments.crop）。",
    );
  });

  it("reads field names from the unified details.fields objects", () => {
    expect(
      editorErrorMessage("validation_error", {
        fields: [
          { field: "maxEge", rule: "extra_forbidden", limit: {}, message: "Extra inputs." },
          { field: "adjustments.exposureEv", rule: "less_than", limit: { le: 5 }, message: "x" },
        ],
      }),
    ).toBe("有参数超出范围，已恢复到上次有效值（maxEge）。");

    expect(
      validationFields({
        fields: [
          { field: "a", rule: "missing", limit: {}, message: "x" },
          { field: "b", rule: "missing", limit: {}, message: "x" },
        ],
      }),
    ).toEqual(["a", "b"]);
    expect(validationFields({ fields: [] })).toEqual([]);
    expect(validationFields({})).toEqual([]);
  });

  it("keeps preview_expired silent", () => {
    expect(isSilentEditorError("preview_expired")).toBe(true);
    expect(isSilentEditorError("network_error")).toBe(false);
    expect(describeEditorError(new ApiClientError("preview_expired", "expired")).message).toBe(
      "",
    );
  });

  it("keeps a superseded render silent", () => {
    expect(isSilentEditorError("render_superseded")).toBe(true);
    expect(
      describeEditorError(new ApiClientError("render_superseded", "newer request")).message,
    ).toBe("");
  });

  it("wraps unknown failures", () => {
    expect(describeEditorError(new Error("boom"))).toEqual({
      code: "unknown_error",
      message: "boom",
      details: {},
    });
  });

  it("keeps the request ID for log correlation", () => {
    const requestId = "27cd3e6046ba4d9b9a8b5f0eec41fa08";
    const result = describeEditorError(
      new ApiClientError("not_found", "Not Found", 404, {}, requestId),
    );

    expect(result.requestId).toBe(requestId);
    expect(result.message).toBe("服务接口不存在，可能是后端版本过旧。请重启 API 后重试。");
  });

  it("shows a safe code and short request ID for unmapped codes", () => {
    const result = describeEditorError(
      new ApiClientError("unexpected_route", "raw", 500, {}, "abcdef1234567890"),
    );

    expect(result.message).toBe(
      "发生未知错误，请稍后重试。（错误码：unexpected_route）（请求 ID：abcdef12）",
    );
  });
});
