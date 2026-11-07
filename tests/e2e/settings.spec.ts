import { expect, test, type Locator, type Page } from "@playwright/test";

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
