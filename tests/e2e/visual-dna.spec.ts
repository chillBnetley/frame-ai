import fs from "node:fs";

import { expect, test } from "@playwright/test";

import {
  ALPHA_FIXTURE_JSON,
  FIXTURE_JSON,
  analysisFixtureJson,
} from "./support";

function fixturePath(metadataPath: string): string {
  const metadata = JSON.parse(fs.readFileSync(metadataPath, "utf8")) as {
    path?: string;
  };
  if (typeof metadata.path !== "string") {
    throw new Error(`${metadataPath} does not contain a fixture path.`);
  }
  return metadata.path;
}

test("applies a published personal style in the workspace", async ({
  page,
}, testInfo) => {
  const styleName = `Workspace ${testInfo.project.name}`;
  const parsed = await page.request.post(
    "/api/v1/personal-styles/custom/parse",
    {
      data: {
        name: styleName,
        description: "低饱和、偏冷的环境色，保留暗部层次，人物肤色自然。",
        avoid: "不要过饱和，高光不要溢出",
      },
    },
  );
  expect(parsed.ok()).toBeTruthy();
  const draft = (await parsed.json()).draft;
  const saved = await page.request.post("/api/v1/personal-styles/custom", {
    data: { draft },
  });
  expect(saved.ok()).toBeTruthy();
  const styleId = (await saved.json()).style.id;
  const published = await page.request.post(
    `/api/v1/personal-styles/${styleId}/status`,
    { data: { status: "published" } },
  );
  expect(published.ok()).toBeTruthy();

  await page.goto(`/master-vision/workspace?style=${styleId}`);
  await expect(
    page.getByRole("heading", { name: "风格创作工作台" }),
  ).toBeVisible();
  await expect(
    page.getByLabel("选择大师、流派或个人风格"),
  ).toHaveValue(styleId);
  await page
    .getByTestId("file-input")
    .setInputFiles(fixturePath(FIXTURE_JSON));
  await expect(page.getByAltText("当前照片")).toBeVisible({ timeout: 90_000 });

  const generate = page.getByRole("button", { name: /生成风格方案/ });
  await expect(generate).toBeEnabled({ timeout: 90_000 });
  await page.getByRole("checkbox", { name: "饱和度" }).check();
  await generate.click();

  const save = page.getByRole("button", { name: /应用并保存/ });
  await expect(save).toBeEnabled({ timeout: 90_000 });
  await save.click();
  await expect(
    page.getByRole("button", { name: "已保存为 AI 创作" }),
  ).toBeDisabled({ timeout: 60_000 });
});

test("mixes two styles, saves an independent profile, and reapplies it", async ({
  page,
}, testInfo) => {
  const personalName = `MixSource ${testInfo.project.name}`;
  const parsed = await page.request.post("/api/v1/personal-styles/custom/parse", {
    data: {
      name: personalName,
      description: "低饱和、偏冷的环境色，保留暗部层次，人物肤色自然。",
      avoid: "不要过饱和，高光不要溢出",
    },
  });
  expect(parsed.ok()).toBeTruthy();
  const draft = (await parsed.json()).draft;
  const savedSource = await page.request.post("/api/v1/personal-styles/custom", {
    data: { draft },
  });
  expect(savedSource.ok()).toBeTruthy();
  const personalId = (await savedSource.json()).style.id;

  await page.goto("/visual-dna/mix");
  await expect(page.getByRole("heading", { name: "混合两种风格" })).toBeVisible();
  await expect(page.getByLabel("风格 A")).toBeEnabled({ timeout: 60_000 });
  await page.getByLabel("风格 A").selectOption("fan_ho");
  await page.getByLabel("风格 B").selectOption(personalId);

  await expect(page.getByRole("heading", { name: "混合预览" })).toBeVisible({
    timeout: 60_000,
  });
  await expect(page.getByText(/保护约束来自两种风格的并集/)).toBeVisible();
  await expect(
    page.getByRole("heading", { name: /检测到 \d+ 处风格冲突/ }),
  ).toBeVisible();

  const mixedName = `Mixed ${testInfo.project.name}`;
  await page.getByLabel("混合风格名称").fill(mixedName);
  await page.getByRole("button", { name: /保存混合风格/ }).click();
  await page.waitForURL(/\/visual-dna\/personal_[a-z0-9]+$/, { timeout: 60_000 });
  await expect(page.getByRole("heading", { name: mixedName })).toBeVisible();
  const mixedId = new URL(page.url()).pathname.split("/").pop() ?? "";
  expect(mixedId).not.toBe(personalId);

  await page.getByRole("button", { name: "发布", exact: true }).click();
  await expect(page.getByText("个人风格已发布。")).toBeVisible({ timeout: 30_000 });

  await page.goto(`/master-vision/workspace?style=${mixedId}`);
  await expect(
    page.getByRole("heading", { name: "风格创作工作台" }),
  ).toBeVisible();
  await expect(page.getByLabel("选择大师、流派或个人风格")).toHaveValue(mixedId);
  await page.getByTestId("file-input").setInputFiles(fixturePath(FIXTURE_JSON));
  await expect(page.getByAltText("当前照片")).toBeVisible({ timeout: 90_000 });

  const generate = page.getByRole("button", { name: /生成风格方案/ });
  await expect(generate).toBeEnabled({ timeout: 90_000 });
  const planResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/api/v1/ai/photographer/plan") &&
      response.request().method() === "POST",
    { timeout: 90_000 },
  );
  await generate.click();
  const plan = await (await planResponse).json();
  expect(plan.styleId).toBe(mixedId);

  const save = page.getByRole("button", { name: /应用并保存/ });
  await expect(save).toBeEnabled({ timeout: 90_000 });
  await save.click();
  await expect(
    page.getByRole("button", { name: "已保存为 AI 创作" }),
  ).toBeDisabled({ timeout: 60_000 });
});

test("creates and refines a style from natural language", async ({ page }, testInfo) => {
  const styleName = `NL ${testInfo.project.name}`;
  const confirmedName = `${styleName} confirmed`;

  await page.goto("/visual-dna/custom");
  await expect(
    page.getByRole("heading", { name: "用自然语言创建个人风格" }),
  ).toBeVisible();

  await page.getByLabel("风格名称").fill(styleName);
  await page
    .getByLabel("风格描述")
    .fill("低饱和、偏冷的环境色，保留暗部层次，人物肤色自然。");
  await page.getByLabel(/不希望出现的效果/).fill("不要过饱和，不要压黑");
  await page.getByRole("button", { name: /解析风格/ }).click();

  await expect(
    page.getByRole("heading", { name: "AI 理解的风格" }),
  ).toBeVisible();
  await expect(page.getByText(/模拟解析/)).toBeVisible();
  await page.getByLabel("确认后的名称").fill(confirmedName);
  await page.getByRole("button", { name: "保存个人风格" }).click();
  await page.waitForURL(/\/visual-dna\/personal_[a-z0-9]+$/, { timeout: 60_000 });
  await expect(page.getByRole("heading", { name: confirmedName })).toBeVisible();

  await page.getByRole("link", { name: "继续调整" }).click();
  await expect(
    page.getByRole("heading", { name: new RegExp(`继续调整「${confirmedName}」`) }),
  ).toBeVisible();
  await page.getByRole("button", { name: "保留更多高光" }).click();
  await page.getByRole("button", { name: "解析修改" }).click();
  await expect(page.getByText("修改预览")).toBeVisible();
  await expect(page.getByText("保留更多高光细节")).toBeVisible();
  await page.getByRole("button", { name: "应用为新版本" }).click();
  await page.waitForURL(/\/visual-dna\/personal_[a-z0-9]+$/, { timeout: 60_000 });
  await expect(page.getByText(/v1\.1/).first()).toBeVisible();
});

test("creates, analyses, fuses, edits, and reviews a personal style", async ({
  page,
}, testInfo) => {
  const styleName = `E2E ${testInfo.project.name}`;
  const updatedDescription = "E2E 更新后的描述，保留暗部层次与自然肤色。";

  await page.goto("/visual-dna/new");
  await expect(
    page.getByRole("heading", { name: "从参考照片创建个人风格" }),
  ).toBeVisible();

  await page.getByLabel("风格名称").fill(styleName);
  await page.getByLabel("一句话描述").fill("低饱和、偏冷，保留真实街头质感。");

  const files = [
    fixturePath(FIXTURE_JSON),
    fixturePath(analysisFixtureJson(testInfo.project.name)),
    fixturePath(ALPHA_FIXTURE_JSON),
  ];
  await page.getByLabel("上传参考照片").setInputFiles(files);
  await expect(page.getByText("已选择 3 张")).toBeVisible({ timeout: 90_000 });

  await page.getByRole("checkbox", { name: /我确认这些照片/ }).check();
  await page.getByRole("button", { name: /创建个人风格/ }).click();
  await page.waitForURL(/\/visual-dna\/personal_[a-z0-9]+/, { timeout: 60_000 });

  await expect(page.getByText(/已完成 3 \/ 3 张/)).toBeVisible({ timeout: 90_000 });
  await page.getByRole("button", { name: "生成个人风格" }).click();
  await expect(
    page.getByRole("heading", { name: "本次融合结果" }),
  ).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/已生成新版本 v1\.1/)).toBeVisible();

  await page.getByRole("link", { name: "编辑风格" }).click();
  await expect(
    page.getByRole("heading", { name: new RegExp(`编辑「${styleName}」`) }),
  ).toBeVisible();
  await page.getByLabel("风格描述").fill(updatedDescription);
  await page.getByRole("button", { name: "保存为新版本" }).click();
  await page.waitForURL(/\/visual-dna\/personal_[a-z0-9]+$/, { timeout: 60_000 });
  await expect(page.getByText(updatedDescription).first()).toBeVisible();

  await page.getByRole("link", { name: "版本历史" }).click();
  await expect(
    page.getByRole("heading", { name: new RegExp(`「${styleName}」版本历史`) }),
  ).toBeVisible();
  await expect(page.getByText("profile.description")).toBeVisible({
    timeout: 30_000,
  });

  const noHorizontalOverflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth <=
      document.documentElement.clientWidth + 1,
  );
  expect(noHorizontalOverflow).toBe(true);
});
