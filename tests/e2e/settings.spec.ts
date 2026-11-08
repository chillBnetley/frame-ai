import { expect, test, type Locator, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

import { openApp } from "./support";

const SETTINGS_PATH = "/api/v1/settings/providers";

interface SettingsSections {
  dialog: Locator;
  vision: Locator;
  decision: Locator;
  planner: Locator;
}

async function openSettings(page: Page): Promise<SettingsSections> {
  await page.getByRole("button", { name: "模型设置" }).click();
  const dialog = page.getByRole("dialog", { name: "模型设置" });
  await expect(dialog).toBeVisible();
  return {
    dialog,
    vision: dialog.getByRole("group", { name: "视觉模型" }),
    decision: dialog.getByRole("group", { name: "决策模型" }),
    planner: dialog.getByRole("group", { name: "规划模型（可选）" }),
  };
}

async function saveAndApply(dialog: Locator): Promise<void> {
  await dialog.getByRole("button", { name: "保存并应用" }).click();
  await expect(dialog.getByText(/已保存并应用/)).toBeVisible();
}

/**
 * Exercises the planner section through the real settings API: the planner
 * starts as a field-by-field copy of the decision provider, accepts an
 * independent model override, survives a dialog reopen without touching
 * vision/decision, falls back when the override is cleared, and disappears on
 * reset together with the other saved overrides.
 */
test("planner settings persist independently and fall back to decision", async ({
  page,
}) => {
  await openApp(page);
  let settings = await openSettings(page);

  // A complete decision provider is the fallback source for every planner field.
  await settings.decision.getByLabel("Provider").selectOption("openai");
  await settings.decision.getByLabel("模型名").fill("decision-model");
  await settings.decision.getByLabel("Base URL").fill("http://127.0.0.1:9/v1");
  await settings.decision.getByLabel("API Key").fill("e2e-decision-key");
  await saveAndApply(settings.dialog);

  // With no planner override, the planner section mirrors the saved decision config.
  await expect(settings.planner.getByLabel("Provider")).toHaveValue("openai");
  await expect(settings.planner.getByLabel("模型名")).toHaveValue("decision-model");
  await expect(settings.planner.getByLabel("Base URL")).toHaveValue(
    "http://127.0.0.1:9/v1",
  );
  await expect(settings.planner.getByLabel("API Key")).toHaveAttribute(
    "placeholder",
    "已从本地保存，留空保持不变",
  );
  await expect(settings.planner.getByText(/留空即跟随决策模型/)).toBeVisible();

  // Only the planner model is submitted; every other planner field still follows decision.
  const plannerSave = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      new URL(request.url()).pathname === SETTINGS_PATH,
  );
  await settings.planner.getByLabel("模型名").fill("planner-model");
  await saveAndApply(settings.dialog);
  expect(JSON.parse((await plannerSave).postData() ?? "{}")).toEqual({
    planner: { model: "planner-model" },
  });

  // Reopening proves the override was persisted and vision/decision were untouched.
  await settings.dialog.getByRole("button", { name: "关闭模型设置" }).click();
  await expect(settings.dialog).toBeHidden();
  settings = await openSettings(page);
  await expect(settings.planner.getByLabel("模型名")).toHaveValue("planner-model");
  await expect(settings.planner.getByLabel("Provider")).toHaveValue("openai");
  await expect(settings.vision.getByLabel("Provider")).toHaveValue("mock");
  await expect(settings.vision.getByLabel("模型名")).toHaveValue("mock-vision");
  await expect(settings.decision.getByLabel("Provider")).toHaveValue("openai");
  await expect(settings.decision.getByLabel("模型名")).toHaveValue("decision-model");
  await expect(settings.decision.getByLabel("Base URL")).toHaveValue(
    "http://127.0.0.1:9/v1",
  );
  await expect(settings.decision.getByLabel("API Key")).toHaveAttribute(
    "placeholder",
    "已从本地保存，留空保持不变",
  );

  // An empty string clears the planner override and falls back per field.
  await settings.planner.getByLabel("模型名").fill("");
  await saveAndApply(settings.dialog);
  await expect(settings.planner.getByLabel("模型名")).toHaveValue("decision-model");

  // Reset also removes the planner group and restores environment defaults.
  await settings.dialog.getByRole("button", { name: "恢复环境变量配置" }).click();
  await settings.dialog.getByRole("button", { name: "确认恢复" }).click();
  await expect(settings.dialog.getByText("已恢复环境变量配置。")).toBeVisible();
  await expect(settings.vision.getByLabel("Provider")).toHaveValue("mock");
  await expect(settings.decision.getByLabel("Provider")).toHaveValue("mock");
  await expect(settings.planner.getByLabel("Provider")).toHaveValue("mock");
  await expect(settings.planner.getByLabel("模型名")).toHaveValue("mock-planner");
});

/**
 * Walks one API key through the encrypted store from the browser: save, read
 * back masked, test the connection, attempt to clear it, then reset.
 *
 * The Base URL points at the closed local port 9, so "测试连接" exercises the real
 * outbound transport without contacting any third-party provider. Every settings
 * response body is checked for the key: the encrypted v2 store must never let it
 * reach the browser, including on the fail-closed clear path.
 */
test("saved API keys stay masked through connection test, clear and reset", async ({
  page,
}) => {
  const apiKey = "e2e-secret-key-never-echoed";
  const bodies: string[] = [];
  page.on("response", (response) => {
    if (new URL(response.url()).pathname.startsWith(SETTINGS_PATH)) {
      void response
        .text()
        .then((text) => bodies.push(text))
        .catch(() => undefined);
    }
  });

  await openApp(page);
  let settings = await openSettings(page);

  await settings.decision.getByLabel("Provider").selectOption("openai");
  await settings.decision.getByLabel("模型名").fill("decision-model");
  await settings.decision.getByLabel("Base URL").fill("http://127.0.0.1:9/v1");
  await settings.decision.getByLabel("API Key").fill(apiKey);
  await saveAndApply(settings.dialog);
  await expect(settings.decision.getByLabel("API Key")).toHaveValue("");
  await expect(settings.decision.getByText(/密钥来源：本地保存/)).toBeVisible();

  // With an explicit data dir the on-disk document is inspected too: v2 with a
  // `secrets` group, no `api_key` field and no plaintext anywhere in the tree.
  const dataDir = process.env.E2E_DATA_DIR;
  if (dataDir) {
    const raw = fs.readFileSync(path.join(dataDir, "provider-settings.json"), "utf8");
    const document = JSON.parse(raw) as {
      version: number;
      decision: Record<string, unknown>;
      secrets: Record<string, { alg: string; nonce: string; ciphertext: string }>;
    };
    expect(document.version).toBe(2);
    expect(document.decision.api_key).toBeUndefined();
    expect(document.secrets.decision.alg).toBe("AES-256-GCM");
    expect(raw).not.toContain(apiKey);
    expect(fs.existsSync(path.join(dataDir, "provider-master-key"))).toBe(true);
    for (const file of fs.readdirSync(dataDir, { recursive: true, withFileTypes: true })) {
      if (file.isFile()) {
        const bytes = fs.readFileSync(path.join(file.parentPath, file.name));
        expect(bytes.includes(Buffer.from(apiKey))).toBe(false);
      }
    }
  }

  // A fresh GET must decrypt the stored key server-side and still mask it.
  await settings.dialog.getByRole("button", { name: "关闭模型设置" }).click();
  await expect(settings.dialog).toBeHidden();
  const reread = page.waitForResponse(
    (response) =>
      response.request().method() === "GET" &&
      new URL(response.url()).pathname === SETTINGS_PATH,
  );
  settings = await openSettings(page);
  const view = JSON.parse(await (await reread).text()) as {
    decision: { hasApiKey: boolean; apiKeySource: string };
    planner: { apiKeySource: string };
  };
  expect(view.decision.hasApiKey).toBe(true);
  expect(view.decision.apiKeySource).toBe("saved");
  expect(view.planner.apiKeySource).toBe("saved");
  await expect(settings.decision.getByLabel("API Key")).toHaveAttribute(
    "placeholder",
    "已从本地保存，留空保持不变",
  );

  // Mock vision succeeds offline; the openai decision/planner fail on the closed port.
  await settings.dialog.getByRole("button", { name: "测试连接" }).click();
  await expect(settings.dialog.getByText(/连接测试完成/)).toBeVisible();
  await expect(settings.dialog.getByText(/视觉模型：连接正常/)).toBeVisible();
  await expect(settings.dialog.getByText(/决策模型：连接失败/)).toBeVisible();
  await expect(settings.dialog.getByText(/规划模型（可选）：连接失败/)).toBeVisible();

  // Clearing the only key of an openai provider is rejected without losing it.
  await settings.decision.getByLabel("清除已保存密钥").check();
  const clearSave = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      new URL(request.url()).pathname === SETTINGS_PATH,
  );
  await settings.dialog.getByRole("button", { name: "保存并应用" }).click();
  expect(JSON.parse((await clearSave).postData() ?? "{}")).toEqual({
    decision: { clearApiKey: true },
  });
  await expect(
    settings.dialog.getByText(/配置不完整或格式不正确：decision\.apiKey/),
  ).toBeVisible();
  await settings.decision.getByLabel("清除已保存密钥").uncheck();
  await expect(settings.decision.getByText(/密钥来源：本地保存/)).toBeVisible();

  // Reset deletes the encrypted document, so no key remains anywhere.
  await settings.dialog.getByRole("button", { name: "恢复环境变量配置" }).click();
  await settings.dialog.getByRole("button", { name: "确认恢复" }).click();
  await expect(settings.dialog.getByText("已恢复环境变量配置。")).toBeVisible();
  await expect(settings.decision.getByLabel("Provider")).toHaveValue("mock");
  await expect(settings.decision.getByText(/密钥来源：未配置/)).toBeVisible();
  await expect(settings.planner.getByText(/密钥来源：未配置/)).toBeVisible();

  expect(bodies.length).toBeGreaterThan(3);
  for (const body of bodies) {
    expect(body).not.toContain(apiKey);
  }
  expect(await page.content()).not.toContain(apiKey);
});
