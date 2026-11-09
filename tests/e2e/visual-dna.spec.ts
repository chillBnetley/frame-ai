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
