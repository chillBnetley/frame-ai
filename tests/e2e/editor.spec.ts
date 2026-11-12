import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

import {
  ALPHA_FIXTURE_JSON,
  ARTIFACTS,
  FIXTURE_JSON,
  SIXTEEN_FIXTURE_JSON,
  openApp,
  requirePython,
  uploadFixture,
  waitForAppReady,
} from "./support";

interface Fixture {
  path: string;
  sha256: string;
  width: number;
  height: number;
  bytes: number;
}

const fixture: Fixture = JSON.parse(fs.readFileSync(FIXTURE_JSON, "utf8"));

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
  await openApp(page);
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
  await openApp(page);
  await uploadFixture(page);

  const toolbar = ["前后对比", "裁切", "导出", "更换照片"];
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

  await page.getByRole("button", { name: "重置", exact: true }).click();
  const resetRevision = page.getByRole("button", { name: /#4 · 重置/ });
  await expect(resetRevision).toHaveAttribute("aria-current", "true");
  await expect(page.getByText("已保存")).toBeVisible();
  await expect(page.getByRole("button", { name: "导出", exact: true })).toBeEnabled();

  await page.getByRole("button", { name: "导出", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "导出图像" });
  await expect(dialog).toBeVisible();
  // The dialog is portalled to <body>. A backdrop-filter ancestor would become
  // its containing block and push it off screen while toBeVisible still passes.
  const viewport = page.viewportSize()!;
  const dialogBox = (await dialog.boundingBox())!;
  expect(dialogBox.x).toBeGreaterThanOrEqual(0);
  expect(dialogBox.y).toBeGreaterThanOrEqual(0);
  expect(dialogBox.x + dialogBox.width).toBeLessThanOrEqual(viewport.width);
  expect(dialogBox.y + dialogBox.height).toBeLessThanOrEqual(viewport.height);

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

test("16-bit PNG upload exports genuinely 16-bit samples", async ({
  page,
}, testInfo) => {
  const sixteenFixture: Fixture = JSON.parse(
    fs.readFileSync(SIXTEEN_FIXTURE_JSON, "utf8"),
  );

  await openApp(page);
  await uploadFixture(page, { fixtureJson: SIXTEEN_FIXTURE_JSON });

  await page.getByRole("button", { name: "导出", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "导出图像" });
  await expect(dialog).toBeVisible();

  await dialog.getByRole("radio", { name: /^PNG/ }).check();
  const sixteenBit = dialog.getByRole("radio", { name: /^16-bit/ });
  await sixteenBit.check();
  await expect(sixteenBit).toBeChecked();

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "开始导出" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.png$/);

  const exportPath = path.join(ARTIFACTS, `sixteen-${testInfo.project.name}.png`);
  await download.saveAs(exportPath);
  await expect(page.getByText(/导出完成/)).toBeVisible({ timeout: 120_000 });

  const verified = JSON.parse(
    execFileSync(
      requirePython(),
      [
        path.join(__dirname, "verify_export.py"),
        exportPath,
        String(sixteenFixture.width),
        String(sixteenFixture.height),
        "png16",
      ],
      { encoding: "utf8" },
    ),
  ) as {
    ok: boolean;
    bit_depth: number;
    unique_levels: number;
    div257_fraction: number;
    icc_description: string;
  };
  expect(verified.ok).toBe(true);
  expect(verified.bit_depth).toBe(16);
  expect(verified.unique_levels).toBeGreaterThan(4096);
  expect(verified.div257_fraction).toBeLessThan(0.5);
  expect(verified.icc_description.toLowerCase()).toContain("srgb");
});

test("transparent PNG export keeps alpha and JPEG composites on white", async ({
  page,
}, testInfo) => {
  const alphaFixture: Fixture = JSON.parse(
    fs.readFileSync(ALPHA_FIXTURE_JSON, "utf8"),
  );

  await openApp(page);
  await uploadFixture(page, { fixtureJson: ALPHA_FIXTURE_JSON });

  await page.getByRole("button", { name: "导出", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "导出图像" });
  await expect(dialog).toBeVisible();

  await dialog.getByRole("radio", { name: /^PNG/ }).check();
  const pngDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: "开始导出" }).click();
  const pngPath = path.join(ARTIFACTS, `alpha-${testInfo.project.name}.png`);
  await (await pngDownload).saveAs(pngPath);
  await expect(page.getByText(/导出完成/)).toBeVisible({ timeout: 120_000 });

  const verifiedPng = JSON.parse(
    execFileSync(
      requirePython(),
      [
        path.join(__dirname, "verify_export.py"),
        pngPath,
        String(alphaFixture.width),
        String(alphaFixture.height),
        "alpha-png",
      ],
      { encoding: "utf8" },
    ),
  ) as {
    ok: boolean;
    mode: string;
    alpha: { levels: number; transparent_fraction: number };
  };
  expect(verifiedPng.ok).toBe(true);
  expect(verifiedPng.mode).toBe("RGBA");
  expect(verifiedPng.alpha.levels).toBeGreaterThan(2);
  expect(verifiedPng.alpha.transparent_fraction).toBeGreaterThan(0);

  await dialog.getByRole("radio", { name: /^JPEG/ }).check();
  const jpegDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: "再次导出" }).click();
  const jpegPath = path.join(ARTIFACTS, `alpha-${testInfo.project.name}.jpg`);
  await (await jpegDownload).saveAs(jpegPath);
  await expect(page.getByText(/导出完成/)).toBeVisible({ timeout: 120_000 });

  const verifiedJpeg = JSON.parse(
    execFileSync(
      requirePython(),
      [
        path.join(__dirname, "verify_export.py"),
        jpegPath,
        String(alphaFixture.width),
        String(alphaFixture.height),
        "alpha-jpeg",
      ],
      { encoding: "utf8" },
    ),
  ) as { ok: boolean; mode: string };
  expect(verifiedJpeg.ok).toBe(true);
  expect(verifiedJpeg.mode).toBe("RGB");
});

test("cancelling an export stops polling and a later export still succeeds", async ({
  page,
}, testInfo) => {
  await openApp(page);
  await uploadFixture(page);
  await waitForAppReady(page);

  // Hold the first status poll so the job is still "running" from the UI's
  // point of view long enough to exercise the cancel path.
  await page.route("**/api/v1/exports/*", async (route) => {
    if (route.request().method() !== "GET") {
      await route.continue();
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 3_000));
    await route.continue().catch(() => undefined);
  });

  await page.getByRole("button", { name: "导出", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "导出图像" })).toBeVisible();
  await page.getByRole("button", { name: "开始导出" }).click();

  await expect(page.getByRole("button", { name: "取消导出" })).toBeVisible();
  await page.getByRole("button", { name: "取消导出" }).click();
  await expect(page.getByText("导出已取消，可以重新开始。")).toBeVisible();

  await page.unroute("**/api/v1/exports/*");

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "开始导出" }).click();
  const download = await downloadPromise;
  await download.saveAs(
    path.join(ARTIFACTS, `cancel-retry-${testInfo.project.name}.jpg`),
  );
  await expect(page.getByText(/导出完成/)).toBeVisible({ timeout: 120_000 });
});

test("deleting a photo removes the original permanently and survives reload", async ({
  page,
}) => {
  await openApp(page);
  await uploadFixture(page);

  const originalHref = await page
    .getByRole("link", { name: "下载原图" })
    .getAttribute("href");
  expect(originalHref).toBeTruthy();
  expect((await page.request.get(originalHref!)).status()).toBe(200);

  await page.getByRole("button", { name: "删除照片", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "删除这张照片？" });
  await expect(dialog).toBeVisible();
  await expect(
    dialog.getByText(/缓存副本会从本机永久删除/),
  ).toBeVisible();

  const deleteResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "DELETE" &&
      new URL(response.url()).pathname.startsWith("/api/v1/images/"),
  );
  await dialog.getByRole("button", { name: "永久删除", exact: true }).click();
  expect((await deleteResponse).status()).toBe(204);

  await expect(
    page.getByText("照片及其编辑会话、分析与缓存副本已从本机永久删除。"),
  ).toBeVisible();
  await expect(page.getByText("拖入一张照片")).toBeVisible();
  await expect(page).not.toHaveURL(/session=/);

  // Deletion also wins over session restore: the original endpoint is gone and
  // a reload cannot bring the editor session back.
  await expect
    .poll(async () => (await page.request.get(originalHref!)).status(), {
      timeout: 15_000,
    })
    .toBe(404);

  await page.reload();
  await waitForAppReady(page);
  await expect(page.getByText("拖入一张照片")).toBeVisible();
  await expect(page.getByRole("heading", { name: "编辑预览" })).toHaveCount(0);
});

test("preview and compare frames show the whole image without clipping", async ({
  page,
}) => {
  await openApp(page);
  await uploadFixture(page);

  const preview = page.getByRole("img", { name: "编辑后的预览" });
  await expect(preview).toBeVisible();
  const previewFit = await preview.evaluate((element) => {
    const image = element as HTMLImageElement;
    const canvas = image.closest(".editor-preview-canvas")!;
    const card = image.closest(".editor-preview-card")!;
    const imageRect = image.getBoundingClientRect();
    const canvasRect = canvas.getBoundingClientRect();
    const cardRect = card.getBoundingClientRect();
    return {
      objectFit: getComputedStyle(image).objectFit,
      insideCanvas:
        imageRect.top >= canvasRect.top - 1 &&
        imageRect.left >= canvasRect.left - 1 &&
        imageRect.bottom <= canvasRect.bottom + 1 &&
        imageRect.right <= canvasRect.right + 1,
      insideCard: imageRect.bottom <= cardRect.bottom + 1,
    };
  });
  expect(previewFit.objectFit).toBe("contain");
  expect(previewFit.insideCanvas).toBe(true);
  expect(previewFit.insideCard).toBe(true);

  await page.getByRole("button", { name: "前后对比" }).click();
  const original = page.getByRole("img", { name: "原图" });
  await expect(original).toBeVisible();
  const compareFit = await original.evaluate((element) => {
    const image = element as HTMLImageElement;
    const frame = image.parentElement!;
    const card = image.closest(".editor-preview-card")!;
    const imageRect = image.getBoundingClientRect();
    const frameRect = frame.getBoundingClientRect();
    const cardRect = card.getBoundingClientRect();
    return {
      objectFit: getComputedStyle(image).objectFit,
      insideFrame:
        imageRect.top >= frameRect.top - 1 &&
        imageRect.left >= frameRect.left - 1 &&
        imageRect.bottom <= frameRect.bottom + 1 &&
        imageRect.right <= frameRect.right + 1,
      insideCard: frameRect.bottom <= cardRect.bottom + 1,
    };
  });
  expect(compareFit.objectFit).toBe("contain");
  expect(compareFit.insideFrame).toBe(true);
  expect(compareFit.insideCard).toBe(true);

  await page.getByRole("button", { name: "退出对比" }).click();
  await page.getByRole("button", { name: "裁切", exact: true }).click();
  const cropImage = page.getByRole("img", { name: "裁切基准画面" });
  await expect(cropImage).toBeVisible();
  const cropFit = await cropImage.evaluate((element) => {
    const image = element as HTMLImageElement;
    const frame = image.parentElement!;
    const card = image.closest(".editor-preview-card")!;
    const frameRect = frame.getBoundingClientRect();
    const cardRect = card.getBoundingClientRect();
    return {
      insideCard: frameRect.bottom <= cardRect.bottom + 1,
      largeEnough: frameRect.width >= 200 && frameRect.height >= 150,
    };
  });
  expect(cropFit.insideCard).toBe(true);
  expect(cropFit.largeEnough).toBe(true);
});
