import { ApiClientError } from "@/lib/api/client";
import { validationFields } from "@/lib/error-messages";
import type {
  GenerativeProviderKind,
  GenerativeProviderSettingsUpdate,
  GenerativeProviderSettingsView,
  ProviderEntryUpdate,
  ProviderEntryView,
  ProviderKind,
} from "@/types/provider-settings";

export interface EntryDraft {
  provider: ProviderKind;
  model: string;
  baseUrl: string;
  apiKey: string;
}

export interface GenerativeDraft {
  provider: GenerativeProviderKind;
  model: string;
  apiKey: string;
  dailyImageLimit: string;
}

export function createEntryDraft(entry: ProviderEntryView): EntryDraft {
  return {
    provider: entry.provider,
    model: entry.model,
    baseUrl: entry.baseUrl,
    apiKey: "",
  };
}

export function createGenerativeDraft(
  entry: GenerativeProviderSettingsView,
): GenerativeDraft {
  return {
    provider: entry.provider,
    model: entry.model,
    apiKey: "",
    dailyImageLimit: String(entry.dailyImageLimit),
  };
}

export function entryUpdate(
  draft: EntryDraft,
  current: ProviderEntryView,
  apiKeyFallback = "",
): ProviderEntryUpdate {
  const patch: ProviderEntryUpdate = {};

  if (draft.provider !== current.provider) {
    patch.provider = draft.provider;
  }

  if (draft.provider === "mock") {
    // Switching to Mock should not leave an old OpenAI model/URL visible after
    // switching back. The stored secret is preserved by the backend.
    if (current.provider !== "mock") {
      patch.model = "";
      patch.baseUrl = "";
    }
  } else {
    const model = draft.model.trim();
    const baseUrl = draft.baseUrl.trim();
    if (model !== current.model) {
      patch.model = model;
    }
    if (baseUrl !== current.baseUrl) {
      patch.baseUrl = baseUrl;
    }
  }

  const apiKey = draft.apiKey.trim();
  if (apiKey !== "") {
    patch.apiKey = apiKey;
  } else if (apiKeyFallback !== "") {
    patch.apiKey = apiKeyFallback;
  }

  return patch;
}

export function generativeUpdate(
  draft: GenerativeDraft,
  current: GenerativeProviderSettingsView,
): GenerativeProviderSettingsUpdate {
  const patch: GenerativeProviderSettingsUpdate = {};

  if (draft.provider !== current.provider) {
    patch.provider = draft.provider;
  }

  if (draft.provider === "dashscope") {
    const model = draft.model.trim();
    if (model !== "" && model !== current.model) {
      patch.model = model;
    }

    const limit = Number.parseInt(draft.dailyImageLimit.trim() || "0", 10);
    if (
      Number.isFinite(limit) &&
      limit >= 0 &&
      limit <= 1000 &&
      limit !== current.dailyImageLimit
    ) {
      patch.dailyImageLimit = limit;
    }

    const apiKey = draft.apiKey.trim();
    if (apiKey !== "") {
      patch.apiKey = apiKey;
    }
  }

  return patch;
}

export function validateEntryDraft(
  draft: EntryDraft,
  options: {
    label: string;
    hasSavedKey: boolean;
    apiKeyFallback?: string;
  },
): string | null {
  if (draft.provider === "mock") {
    return null;
  }
  if (draft.model.trim() === "") {
    return `${options.label}：请填写模型名。`;
  }
  if (draft.baseUrl.trim() === "") {
    return `${options.label}：请填写 Base URL。`;
  }
  if (
    draft.apiKey.trim() === "" &&
    !options.hasSavedKey &&
    (options.apiKeyFallback ?? "") === ""
  ) {
    return `${options.label}：请填写 API Key。`;
  }
  return null;
}

export function validateGenerativeDraft(
  draft: GenerativeDraft,
  options: { hasSavedKey: boolean },
): string | null {
  if (draft.provider === "mock") {
    return null;
  }
  if (draft.model.trim() === "") {
    return "生成式图像模型：请填写模型名。";
  }
  if (draft.apiKey.trim() === "" && !options.hasSavedKey) {
    return "生成式图像模型：请填写百炼 API Key。";
  }
  return null;
}

export function isEntryReady(entry: ProviderEntryView): boolean {
  return entry.provider !== "mock" && entry.hasApiKey;
}

export function areModelsReady(
  view: { vision: ProviderEntryView; decision: ProviderEntryView } | null,
): boolean {
  return view !== null && isEntryReady(view.vision) && isEntryReady(view.decision);
}

export function describeProviderError(error: unknown): string {
  if (error instanceof ApiClientError) {
    if (error.code === "invalid_provider_settings") {
      const fields = validationFields(error.details);
      return fields.length > 0
        ? `配置不完整或格式不正确：${fields.join("、")}`
        : "配置不完整或格式不正确，请检查所有字段。";
    }
    if (error.code === "provider_settings_unavailable") {
      return "设置服务尚未就绪，请稍后重试。";
    }
    if (error.code === "provider_settings_write_failed") {
      return "配置无法写入本机数据目录，请检查磁盘权限。";
    }
    return error.message;
  }
  return error instanceof Error ? error.message : "设置操作失败，请稍后重试。";
}

export function keyPlaceholder(source: ProviderEntryView["apiKeySource"]): string {
  if (source === "saved") {
    return "已从本地保存，留空保持不变";
  }
  if (source === "environment") {
    return "使用环境变量中的密钥，留空保持不变";
  }
  return "sk-…";
}
