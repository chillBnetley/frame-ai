import { describe, expect, it } from "vitest";

import { ApiClientError } from "@/lib/api/client";
import { describeGenerativeError, type GenerativeErrorCategory } from "@/lib/generative-errors";

const CATEGORY_LABELS: Record<GenerativeErrorCategory, string> = {
  network: "网络错误",
  provider: "Provider 错误",
  image_format: "图片格式错误",
  mask: "蒙版错误",
  size_limit: "超出尺寸限制",
  task_limit: "超出任务限制",
  generation_failed: "生成失败",
  save_failed: "保存失败",
};

/** Every `generative_*` code the API can return, harvested from services/api. */
const BACKEND_GENERATIVE_CODES = [
  "generative_base_changed",
  "generative_base_geometry_unsupported",
  "generative_blank_output",
  "generative_capability_unsupported",
  "generative_consent_required",
  "generative_empty_output",
  "generative_input_too_large",
  "generative_instruction_required",
  "generative_internal_error",
  "generative_invalid_input",
  "generative_invalid_output",
  "generative_invalid_output_size",
  "generative_mask_conflict",
  "generative_mask_coverage",
  "generative_mask_definition_invalid",
  "generative_mask_empty",
  "generative_mask_invalid",
  "generative_mask_kind_unsupported",
  "generative_mask_mismatch",
  "generative_mask_missing",
  "generative_mask_not_found",
  "generative_mask_required",
  "generative_mask_semantic_base_unsupported",
  "generative_mask_service",
  "generative_mask_size_mismatch",
  "generative_mask_storage_error",
  "generative_no_visible_change",
  "generative_outpaint_invalid",
  "generative_outpaint_params_required",
  "generative_output_too_large",
  "generative_provider_auth_failed",
  "generative_provider_budget_exceeded",
  "generative_provider_endpoint_error",
  "generative_provider_error",
  "generative_provider_failed",
  "generative_provider_invalid_response",
  "generative_provider_rate_limited",
  "generative_provider_response_too_large",
  "generative_provider_timeout",
  "generative_provider_unavailable",
  "generative_provider_usage_unavailable",
  "generative_result_corrupted",
  "generative_result_not_candidate",
  "generative_result_not_found",
  "generative_retry_not_allowed",
  "generative_service",
  "generative_storage_budget_exceeded",
  "generative_storage_error",
  "generative_task_not_found",
  "generative_task_not_ready",
  "generative_timeout",
  "generative_unavailable",
];

/** Codes the transport layer raises before or instead of an API response. */
const CLIENT_CODES = [
  "request_timeout",
  "network_error",
  "origin_not_allowed",
  "server_busy",
  "validation_error",
  "storage_error",
  "image_too_many_pixels",
  "invalid_image",
  "unsupported_media_type",
  "animated_not_supported",
  "mime_mismatch",
  "empty_file",
];

function view(code: string) {
  return describeGenerativeError(new ApiClientError(code, "raw backend message", 500, {}, null));
}

describe("describeGenerativeError category mapping", () => {
  it.each([...BACKEND_GENERATIVE_CODES, ...CLIENT_CODES])("classifies %s", (code) => {
    const described = view(code);

    expect(described).not.toBeNull();
    expect(described?.category).not.toBeNull();
    expect(Object.keys(CATEGORY_LABELS)).toContain(described?.category);
    expect(described?.label).toBe(CATEGORY_LABELS[described?.category as GenerativeErrorCategory]);
    expect(described?.message.length).toBeGreaterThan(4);
    expect(described?.nextStep.length).toBeGreaterThan(4);
    expect(described?.code).toBe(code);
  });

  it("keeps the eight product categories distinct", () => {
    const samples: Array<[string, GenerativeErrorCategory]> = [
      ["network_error", "network"],
      ["generative_provider_rate_limited", "provider"],
      ["unsupported_media_type", "image_format"],
      ["generative_mask_empty", "mask"],
      ["generative_output_too_large", "size_limit"],
      ["generative_consent_required", "task_limit"],
      ["generative_blank_output", "generation_failed"],
      ["generative_storage_error", "save_failed"],
    ];

    for (const [code, category] of samples) {
      expect(view(code)?.category).toBe(category);
    }
    expect(new Set(samples.map(([, category]) => category)).size).toBe(8);
  });

  it("routes an unknown generative code to the generation failure bucket", () => {
    const described = view("generative_something_new");

    expect(described?.category).toBe("generation_failed");
    expect(described?.message).toBe("raw backend message");
  });

  it("reports the request id in short form for support", () => {
    const error = new ApiClientError("generative_service", "boom", 500, {}, "a1b2c3d4e5f6");

    expect(describeGenerativeError(error)?.requestId).toBe("a1b2c3d4");
  });

  it("treats a code-less message as guidance rather than a fault", () => {
    const described = describeGenerativeError("请先选择或绘制消除区域蒙版。");

    expect(described).toEqual({
      category: null,
      label: "提示",
      message: "请先选择或绘制消除区域蒙版。",
      nextStep: "",
      code: null,
      requestId: null,
    });
  });

  it("accepts the task controller payload shape", () => {
    const described = describeGenerativeError({
      code: "generative_mask_missing",
      message: "mask gone",
      requestId: null,
    });

    expect(described?.category).toBe("mask");
    expect(described?.requestId).toBeNull();
  });

  it("returns null when there is nothing to describe", () => {
    expect(describeGenerativeError(null)).toBeNull();
    expect(describeGenerativeError(undefined)).toBeNull();
    expect(describeGenerativeError({})).toBeNull();
    expect(describeGenerativeError(42)).toBeNull();
  });

  it("falls back to a plain error message", () => {
    expect(describeGenerativeError(new Error("socket hung up"))?.message).toBe("socket hung up");
  });
});
