import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";

import { FIXTURE_JSON } from "./support";

interface Fixture {
  path: string;
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

async function scrollPanelToBottom(page: Page): Promise<void> {
  await page.getByTestId("adjustment-panel-scroll").evaluate((node) => {
    node.scrollTo({ top: node.scrollHeight });
  });
}

async function scrollPageToBottom(page: Page): Promise<void> {
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
}

// Stage 4 keeps appending panels to the parameter column, so the bottom-most control
// is asserted by position instead of by a hardcoded label.
function bottomSlider(page: Page) {
  return page
    .getByTestId("adjustment-panel-scroll")
    .locator('input[type="number"]')
    .last();
}

test.describe("desktop preview visibility", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("keeps the sticky preview visible while adjusting the bottom sliders", async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280x800", "desktop viewport only");

    await uploadFixture(page);
    await page.getByTestId("adjustment-panel-scroll").scrollIntoViewIfNeeded();
    await scrollPanelToBottom(page);

    await expect(bottomSlider(page)).toBeInViewport();
    await expect(page.getByAltText("编辑后的预览")).toBeInViewport({ ratio: 0.6 });

    const header = await page.locator("header").boundingBox();
    const preview = await page.getByAltText("编辑后的预览").boundingBox();
    expect(header).not.toBeNull();
    expect(preview).not.toBeNull();
    expect(preview!.y).toBeGreaterThanOrEqual(header!.height - 1);

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    );
    expect(overflow).toBe(false);
  });
});

test.describe("short desktop preview visibility", () => {
  test.use({ viewport: { width: 1280, height: 640 } });

  test("keeps at least half of the preview visible at the panel bottom", async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-1280x800", "desktop viewport only");

    await uploadFixture(page);
    await page.getByTestId("adjustment-panel-scroll").scrollIntoViewIfNeeded();
    await scrollPanelToBottom(page);

    await expect(bottomSlider(page)).toBeInViewport();
    await expect(page.getByAltText("编辑后的预览")).toBeInViewport({ ratio: 0.5 });

    const header = await page.locator("header").boundingBox();
    const preview = await page.getByAltText("编辑后的预览").boundingBox();
    expect(preview!.y).toBeGreaterThanOrEqual(header!.height - 1);
  });
});

test.describe("mobile preview monitor", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("shows the monitor at the bottom sliders and returns to the main preview", async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name !== "mobile-390x844", "mobile viewport only");

    let renderRequests = 0;
    page.on("request", (request) => {
      if (request.method() === "POST" && request.url().includes("/render")) {
        renderRequests += 1;
      }
    });

    await uploadFixture(page);
    await page.getByAltText("编辑后的预览").scrollIntoViewIfNeeded();
    await expect(page.getByTestId("preview-monitor")).toHaveCount(0);

    const requestsBeforeMonitor = renderRequests;
    const grain = page.getByRole("spinbutton", { name: "颗粒", exact: true });
    await grain.scrollIntoViewIfNeeded();
    await expect(page.getByTestId("preview-monitor")).toBeVisible();
    expect(renderRequests).toBe(requestsBeforeMonitor);
    await expect(page.getByRole("button", { name: "返回编辑预览" })).toBeVisible();
    await expect(grain).toBeInViewport();

    const monitor = page.getByTestId("preview-monitor");
    await expect(monitor.locator("img")).toHaveAttribute("alt", "");
    const monitorBox = await monitor.boundingBox();
    const header = await page.locator("header").boundingBox();
    expect(monitorBox!.y).toBeGreaterThanOrEqual(header!.height - 1);

    await page.getByRole("button", { name: "返回编辑预览" }).click();
    await expect(page.getByAltText("编辑后的预览")).toBeInViewport({ ratio: 0.6 });
    await expect(page.getByTestId("preview-monitor")).toHaveCount(0);
  });

  test("hides the monitor in compare, crop, and export states", async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name !== "mobile-390x844", "mobile viewport only");

    await uploadFixture(page);

    await page.getByRole("button", { name: "前后对比", exact: true }).click();
    await expect(page.getByAltText("编辑后的版本")).toBeVisible({ timeout: 60_000 });
    await scrollPageToBottom(page);
    await expect(page.getByTestId("preview-monitor")).toHaveCount(0);
    await page.getByRole("button", { name: "退出对比" }).click();

    await page.getByRole("button", { name: "裁切", exact: true }).click();
    await expect(page.getByRole("button", { name: "应用裁切" })).toBeVisible();
    await scrollPageToBottom(page);
    await expect(page.getByTestId("preview-monitor")).toHaveCount(0);
    await page.getByRole("button", { name: "取消", exact: true }).click();

    await page.getByRole("button", { name: "导出", exact: true }).click();
    await expect(page.getByRole("dialog", { name: "导出图像" })).toBeVisible();
    await scrollPageToBottom(page);
    await expect(page.getByTestId("preview-monitor")).toHaveCount(0);
    await page.getByRole("button", { name: "关闭导出对话框" }).click();
  });
});

test.describe("narrow mobile preview monitor", () => {
  test.use({ viewport: { width: 320, height: 568 } });

  test("shows the monitor without horizontal overflow or covering the slider", async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name !== "mobile-390x844", "mobile viewport only");

    await uploadFixture(page);
    const rotation = page.getByRole("spinbutton", { name: "旋转", exact: true });
    await rotation.scrollIntoViewIfNeeded();

    await expect(page.getByTestId("preview-monitor")).toBeVisible();
    await expect(rotation).toBeInViewport();

    const sliderBox = await page.getByRole("slider", { name: "旋转" }).boundingBox();
    const numberBox = await rotation.boundingBox();
    expect(sliderBox!.height).toBeGreaterThanOrEqual(43.5);
    expect(numberBox!.height).toBeGreaterThanOrEqual(43.5);

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    );
    expect(overflow).toBe(false);
  });
});
