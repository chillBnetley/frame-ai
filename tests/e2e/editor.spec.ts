import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

import { ARTIFACTS, FIXTURE_JSON, requirePython } from "./support";

interface Fixture {
  path: string;
  sha256: string;
  width: number;
  height: number;
  bytes: number;
}

const fixture: Fixture = JSON.parse(fs.readFileSync(FIXTURE_JSON, "utf8"));

async function uploadFixture(page: Page): Promise<void> {
  await page.goto("/");
  const responsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/v1/images" &&
      response.status() === 201,
  );
  await page.getByTestId("file-input").setInputFiles(fixture.path);
  await responsePromise;
  await expect(page.getByRole("heading", { name: "编辑预览" })).toBeVisible();
  await expect(page.getByAltText("编辑后的预览")).toBeVisible({ timeout: 60_000 });
}

async function setAdjustment(page: Page, name: string, value: string): Promise<void> {
  const input = page.getByRole("spinbutton", { name, exact: true });
  await input.fill(value);
  await expect(page.getByText("有未保存的调整")).toBeVisible();
  await input.press("Enter");
  await expect(page.getByText("已保存")).toBeVisible();
}

test("keyboard slider adjustments keep focus and merge into one revision", async ({
  page,
}) => {
  await uploadFixture(page);

  const slider = page.getByRole("slider", { name: "曝光", exact: true });
  await slider.focus();
  await expect(slider).toBeFocused();

  for (let press = 0; press < 5; press += 1) {
    await page.keyboard.press("ArrowRight");
  }

  await expect(slider).toBeFocused();
  await expect(slider).toHaveAttribute("aria-valuetext", "+0.05 EV");
  await expect(slider).toBeEnabled();

  await expect(page.getByRole("button", { name: /#2 · 手动/ })).toBeVisible({
    timeout: 60_000,
  });
  await expect(page.getByRole("button", { name: /#3 · 手动/ })).toHaveCount(0);
  await expect(slider).toBeFocused();
});

test("upload, adjust, compare, undo/redo/reset, and export JPEG", async ({
  page,
}, testInfo) => {
  await uploadFixture(page);

  const toolbar = ["前后对比", "裁切", "导出", "更换照片", "重新开始"];
  for (const name of toolbar) {
    const box = await page
      .getByRole("button", { name, exact: true })
      .first()
      .boundingBox();
    expect(box, `${name} should be visible`).not.toBeNull();
    expect(box!.height).toBeGreaterThanOrEqual(43.5);
  }

  await setAdjustment(page, "曝光", "1");
  await expect(page.getByRole("button", { name: /#2 · 手动/ })).toBeVisible();
  await setAdjustment(page, "饱和度", "-100");
  await expect(page.getByRole("button", { name: /#3 · 手动/ })).toBeVisible();

  await page.getByRole("button", { name: "前后对比", exact: true }).click();
  await expect(page.getByAltText("编辑后的版本")).toBeVisible({ timeout: 60_000 });
  const hold = page.getByRole("button", { name: /查看原图/ });
  await hold.focus();
  await page.keyboard.down("Space");
  await expect(hold).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByAltText("编辑后的版本")).toHaveCount(0);
  await page.keyboard.up("Space");
  await page.getByRole("button", { name: "退出对比" }).click();

  await page.getByRole("button", { name: "撤销" }).click();
  await expect(page.getByRole("button", { name: "重做" })).toHaveAttribute(
    "aria-disabled",
    "false",
  );
  await page.getByRole("button", { name: "重做" }).click();
  await expect(page.getByRole("button", { name: "撤销" })).toHaveAttribute(
    "aria-disabled",
    "false",
  );

  await page.getByRole("button", { name: "重置" }).click();
  const resetRevision = page.getByRole("button", { name: /#4 · 重置/ });
  await expect(resetRevision).toHaveAttribute("aria-current", "true");
  await expect(page.getByText("已保存")).toBeVisible();
  await expect(page.getByRole("button", { name: "导出", exact: true })).toBeEnabled();

  await page.getByRole("button", { name: "导出", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "导出图像" });
  await expect(dialog).toBeVisible();

  const exportPath = path.join(ARTIFACTS, `${testInfo.project.name}.jpg`);
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "开始导出" }).click();
  const download = await downloadPromise;
  await download.saveAs(exportPath);
  await expect(page.getByText(/导出完成/)).toBeVisible({ timeout: 120_000 });

  const verified = JSON.parse(
    execFileSync(
      requirePython(),
      [
        path.join(__dirname, "verify_export.py"),
        exportPath,
        String(fixture.width),
        String(fixture.height),
      ],
      { encoding: "utf8" },
    ),
  ) as { ok: boolean; exif_keys: string[]; icc_description: string };
  expect(verified.ok).toBe(true);
  expect(verified.exif_keys).toEqual([]);
  expect(verified.icc_description.toLowerCase()).toContain("srgb");

  const originalHref = await page
    .getByRole("link", { name: "下载原图" })
    .getAttribute("href");
  expect(originalHref).toBeTruthy();
  const originalResponse = await page.request.get(originalHref!);
  expect(originalResponse.ok()).toBe(true);
  const originalBytes = await originalResponse.body();
  const originalSha = crypto.createHash("sha256").update(originalBytes).digest("hex");
  expect(originalSha).toBe(fixture.sha256);

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1,
  );
  expect(overflow, "page must not scroll horizontally").toBe(false);
});
