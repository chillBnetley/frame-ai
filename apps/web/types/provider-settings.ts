export type ProviderKind = "mock" | "openai";
export type GenerativeProviderKind = "mock" | "dashscope";
export type ApiKeySource = "saved" | "environment" | "none";

export interface ProviderEntryView {
  provider: ProviderKind;
  model: string;
  baseUrl: string;
  hasApiKey: boolean;
  apiKeySource: ApiKeySource;
}

export type PlannerProviderSettingsView = ProviderEntryView;

export interface GenerativeProviderSettingsView {
  provider: GenerativeProviderKind;
  model: string;
  baseUrl: string;
  hasApiKey: boolean;
  apiKeySource: ApiKeySource;
  dailyImageLimit: number;
  ready: boolean;
}

export interface ProviderSettingsView {
  vision: ProviderEntryView;
  decision: ProviderEntryView;
  planner: PlannerProviderSettingsView;
  generative: GenerativeProviderSettingsView;
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

export type PlannerProviderSettingsUpdate = ProviderEntryUpdate;

export interface GenerativeProviderSettingsUpdate {
  provider?: GenerativeProviderKind;
  model?: string;
  baseUrl?: string;
  apiKey?: string;
  clearApiKey?: boolean;
  dailyImageLimit?: number;
}

export interface ProviderSettingsUpdate {
  vision?: ProviderEntryUpdate;
  decision?: ProviderEntryUpdate;
  planner?: PlannerProviderSettingsUpdate;
  generative?: GenerativeProviderSettingsUpdate;
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
  planner: ProviderTestResult;
}
