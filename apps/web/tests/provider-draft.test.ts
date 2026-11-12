import { describe, expect, it } from "vitest";

import {
  areModelsReady,
  entryUpdate,
  generativeUpdate,
  isEntryReady,
  validateEntryDraft,
  validateGenerativeDraft,
  type EntryDraft,
  type GenerativeDraft,
} from "@/features/onboarding/provider-draft";
import type {
  GenerativeProviderSettingsView,
  ProviderEntryView,
} from "@/types/provider-settings";

function entry(overrides: Partial<ProviderEntryView> = {}): ProviderEntryView {
  return {
    provider: "mock",
    model: "mock-vision",
    baseUrl: "",
    hasApiKey: false,
    apiKeySource: "none",
    ...overrides,
  };
}

function generative(
  overrides: Partial<GenerativeProviderSettingsView> = {},
): GenerativeProviderSettingsView {
  return {
    provider: "mock",
    model: "wanx2.1-imageedit",
    baseUrl: "",
    hasApiKey: false,
    apiKeySource: "none",
    dailyImageLimit: 0,
    ready: true,
    ...overrides,
  };
}

function draft(overrides: Partial<EntryDraft> = {}): EntryDraft {
  return {
    provider: "mock",
    model: "",
    baseUrl: "",
    apiKey: "",
    ...overrides,
  };
}

function generativeDraft(
  overrides: Partial<GenerativeDraft> = {},
): GenerativeDraft {
  return {
    provider: "mock",
    model: "",
    apiKey: "",
    dailyImageLimit: "0",
    ...overrides,
  };
}

describe("provider draft updates", () => {
  it("writes the full OpenAI connection when switching from Mock", () => {
    expect(
      entryUpdate(
        draft({
          provider: "openai",
          model: "qwen-vl-plus",
          baseUrl: "https://api.example.com/v1",
          apiKey: "sk-test",
        }),
        entry(),
      ),
    ).toEqual({
      provider: "openai",
      model: "qwen-vl-plus",
      baseUrl: "https://api.example.com/v1",
      apiKey: "sk-test",
    });
  });

  it("clears the old OpenAI model and URL when switching to Mock", () => {
    expect(
      entryUpdate(
        draft({ provider: "mock" }),
        entry({
          provider: "openai",
          model: "gpt-4o",
          baseUrl: "https://api.example.com/v1",
          hasApiKey: true,
          apiKeySource: "saved",
        }),
      ),
    ).toEqual({ provider: "mock", model: "", baseUrl: "" });
  });

  it("reuses the key entered in the previous step", () => {
    const current = entry({
      provider: "openai",
      model: "gpt-4o",
      baseUrl: "https://api.example.com/v1",
      hasApiKey: false,
    });

    expect(
      entryUpdate(
        draft({
          provider: "openai",
          model: "gpt-4o",
          baseUrl: "https://api.example.com/v1",
        }),
        current,
        "sk-shared",
      ),
    ).toEqual({ apiKey: "sk-shared" });
  });

  it("keeps an already saved key untouched when nothing changed", () => {
    const current = entry({
      provider: "openai",
      model: "gpt-4o",
      baseUrl: "https://api.example.com/v1",
      hasApiKey: true,
      apiKeySource: "saved",
    });

    expect(
      entryUpdate(
        draft({
          provider: "openai",
          model: "gpt-4o",
          baseUrl: "https://api.example.com/v1",
        }),
        current,
      ),
    ).toEqual({});
  });

  it("saves the optional DashScope key and daily limit", () => {
    expect(
      generativeUpdate(
        generativeDraft({
          provider: "dashscope",
          model: "wanx2.1-imageedit",
          apiKey: "sk-dash",
        }),
        generative(),
      ),
    ).toEqual({ provider: "dashscope", apiKey: "sk-dash" });

    expect(
      generativeUpdate(
        generativeDraft({
          provider: "dashscope",
          model: "wanx2.1-imageedit",
          dailyImageLimit: "5",
        }),
        generative({
          provider: "dashscope",
          hasApiKey: true,
          apiKeySource: "saved",
        }),
      ),
    ).toEqual({ dailyImageLimit: 5 });
  });
});

describe("provider draft validation", () => {
  it("requires model, base URL and key for an OpenAI connection", () => {
    expect(
      validateEntryDraft(draft({ provider: "openai" }), {
        label: "视觉模型",
        hasSavedKey: false,
      }),
    ).toContain("模型名");

    expect(
      validateEntryDraft(
        draft({
          provider: "openai",
          model: "gpt-4o",
          baseUrl: "https://api.example.com/v1",
        }),
        { label: "视觉模型", hasSavedKey: false },
      ),
    ).toContain("API Key");

    expect(
      validateEntryDraft(
        draft({
          provider: "openai",
          model: "gpt-4o",
          baseUrl: "https://api.example.com/v1",
        }),
        { label: "视觉模型", hasSavedKey: false, apiKeyFallback: "sk-shared" },
      ),
    ).toBeNull();
  });

  it("does not require fields for Mock", () => {
    expect(
      validateEntryDraft(draft({ provider: "mock" }), {
        label: "视觉模型",
        hasSavedKey: false,
      }),
    ).toBeNull();
    expect(
      validateGenerativeDraft(generativeDraft({ provider: "mock" }), {
        hasSavedKey: false,
      }),
    ).toBeNull();
  });

  it("requires a key for DashScope", () => {
    expect(
      validateGenerativeDraft(
        generativeDraft({ provider: "dashscope", model: "wanx2.1-imageedit" }),
        { hasSavedKey: false },
      ),
    ).toContain("百炼 API Key");
  });
});

describe("model readiness", () => {
  it("only treats a real provider with a key as ready", () => {
    expect(isEntryReady(entry())).toBe(false);
    expect(
      isEntryReady(
        entry({
          provider: "openai",
          hasApiKey: true,
          apiKeySource: "saved",
        }),
      ),
    ).toBe(true);
    expect(
      areModelsReady({
        vision: entry({ provider: "openai", hasApiKey: true }),
        decision: entry({ provider: "openai", hasApiKey: true }),
      }),
    ).toBe(true);
    expect(
      areModelsReady({
        vision: entry({ provider: "openai", hasApiKey: true }),
        decision: entry(),
      }),
    ).toBe(false);
    expect(areModelsReady(null)).toBe(false);
  });
});
