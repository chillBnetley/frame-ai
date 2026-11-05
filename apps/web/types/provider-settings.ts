export type ProviderKind = "mock" | "openai";
export type ApiKeySource = "saved" | "environment" | "none";

export interface ProviderEntryView {
  provider: ProviderKind;
  model: string;
  baseUrl: string;
  hasApiKey: boolean;
  apiKeySource: ApiKeySource;
}

export interface ProviderSettingsView {
  vision: ProviderEntryView;
  decision: ProviderEntryView;
  isMock: boolean;
  hasSavedOverrides: boolean;
}

export interface ProviderEntryUpdate {
  provider?: ProviderKind;
  model?: string;
  baseUrl?: string;
  apiKey?: string;
  clearApiKey?: boolean;
}

export interface ProviderSettingsUpdate {
  vision?: ProviderEntryUpdate;
  decision?: ProviderEntryUpdate;
}

export interface ProviderTestResult {
  ok: boolean;
  provider: ProviderKind;
  model: string;
  latencyMs: number;
  code?: string | null;
  message?: string | null;
}

export interface ProviderTestResponse {
  vision: ProviderTestResult;
  decision: ProviderTestResult;
}
