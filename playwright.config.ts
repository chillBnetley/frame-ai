import { defineConfig, devices } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { ROOT, requirePython } from "./tests/e2e/support";

const API_PORT = Number(process.env.E2E_API_PORT ?? 8010);
const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 3010);
const API_URL = process.env.E2E_API_URL ?? `http://127.0.0.1:${API_PORT}`;
const BASE_URL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${WEB_PORT}`;
const CHANNEL = process.env.E2E_BROWSER_CHANNEL || undefined;
const DATA_DIR =
  process.env.E2E_DATA_DIR ?? fs.mkdtempSync(path.join(os.tmpdir(), "frame-ai-e2e-"));
process.env.E2E_DATA_DIR = DATA_DIR;

const webCommand =
  process.platform === "win32"
    ? `cmd.exe /c npm run dev -- --port ${WEB_PORT}`
    : `npm run dev -- --port ${WEB_PORT}`;

const webServer = [
  {
    command: `"${requirePython()}" -m uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT} --log-level warning`,
    cwd: path.join(ROOT, "services", "api"),
    env: {
      FRAME_DATA_DIR: DATA_DIR,
      FRAME_LOG_LEVEL: "WARNING",
      FRAME_ALLOWED_ORIGINS:
        process.env.E2E_FRAME_ALLOWED_ORIGINS ?? BASE_URL,
      FRAME_MOCK_SCENARIO: process.env.E2E_MOCK_SCENARIO ?? "backlit",
      FRAME_PROVIDER_URL_POLICY: "allow-local",
      FRAME_PROVIDER_ALLOW_INSECURE_HTTP: "true",
      FRAME_API_AUTH_ENABLED: "true",
      PYTHONUNBUFFERED: "1",
    },
    url: `${API_URL}/`,
    reuseExistingServer: false,
    timeout: 120_000,
  },
];

if (!process.env.E2E_BASE_URL) {
  webServer.push({
    command: webCommand,
    cwd: path.join(ROOT, "apps", "web"),
    env: {
      API_INTERNAL_URL: API_URL,
      NEXT_TELEMETRY_DISABLED: "1",
      FRAME_DATA_DIR: DATA_DIR,
    },
    url: BASE_URL,
    reuseExistingServer: false,
    timeout: 180_000,
  });
}

export default defineConfig({
  testDir: "./tests/e2e",
  globalSetup: "./tests/e2e/global-setup.ts",
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 30_000 },
  outputDir: "test-results",
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: BASE_URL,
    channel: CHANNEL,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "desktop-1280x800",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
    {
      name: "mobile-390x844",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 390, height: 844 },
        isMobile: true,
        hasTouch: true,
      },
    },
  ],
  webServer,
});
