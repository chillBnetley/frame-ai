import type {
  ProviderSettingsUpdate,
  ProviderSettingsView,
  ProviderTestResponse,
} from "@/types/provider-settings";

import { apiJson } from "./client";

const BASE = "/api/v1/settings/providers";
const TEST_TIMEOUT_MS = 60_000;

export async function fetchProviderSettings(
  signal?: AbortSignal,
): Promise<ProviderSettingsView> {
  return apiJson<ProviderSettingsView>(BASE, { cache: "no-store" }, { signal });
}

export async function saveProviderSettings(
  update: ProviderSettingsUpdate,
  signal?: AbortSignal,
): Promise<ProviderSettingsView> {
  return apiJson<ProviderSettingsView>(
    BASE,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(update),
    },
    { signal },
  );
}

export async function testProviderSettings(
  update: ProviderSettingsUpdate,
  signal?: AbortSignal,
): Promise<ProviderTestResponse> {
  return apiJson<ProviderTestResponse>(
    `${BASE}/test`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(update),
    },
    { signal, timeoutMs: TEST_TIMEOUT_MS },
  );
}

export async function resetProviderSettings(
  signal?: AbortSignal,
): Promise<ProviderSettingsView> {
  return apiJson<ProviderSettingsView>(
    `${BASE}/reset`,
    { method: "POST" },
    { signal },
  );
}
