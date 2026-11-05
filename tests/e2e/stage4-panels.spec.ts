import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";

import { FIXTURE_JSON } from "./support";

interface Fixture {
  path: string;
  width: number;
  height: number;
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

async function commitAdjustment(page: Page, name: string, value: string): Promise<void> {
  const input = page.getByRole("spinbutton", { name, exact: true });
  await input.fill(value);
  await expect(page.getByText("有未保存的调整")).toBeVisible();
  await input.press("Enter");
  await expect(page.getByText("已保存")).toBeVisible();
}

async function drag(
  page: Page,
  target: { x: number; y: number },
  delta: { x: number; y: number },
): Promise<void> {
  await page.mouse.move(target.x, target.y);
  await page.mouse.down();
  await page.mouse.move(target.x + delta.x, target.y + delta.y, { steps: 8 });
  await page.mouse.up();
}

test("curve, HSL, colour grading, and local mask workflow", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name.startsWith("mobile"), "desktop interaction coverage");
  await uploadFixture(page);

  const surface = page.getByTestId("curve-surface");
  const surfaceBox = await surface.boundingBox();
  expect(surfaceBox, "curve surface should be laid out").not.toBeNull();
  await surface.click({
    position: { x: surfaceBox!.width * 0.55, y: surfaceBox!.height * 0.45 },
  });

  const nodes = page.locator('[data-testid^="curve-node-"]');
  await expect(nodes).toHaveCount(3);
  await expect(page.getByTestId("curve-node-1")).toHaveAttribute("role", "button");
  await expect(page.getByText("已保存")).toBeVisible();

  const node = page.getByTestId("curve-node-1");
  const nodeBox = await node.boundingBox();
  expect(nodeBox, "middle curve node should be visible").not.toBeNull();
  const beforeDrag = await node.getAttribute("aria-label");
  await drag(
    page,
    { x: nodeBox!.x + nodeBox!.width / 2, y: nodeBox!.y + nodeBox!.height / 2 },
    { x: 18, y: -16 },
  );
  await expect(page.getByText("已保存")).toBeVisible();
  expect(await node.getAttribute("aria-label")).not.toBe(beforeDrag);

  await page.getByRole("button", { name: "删除节点", exact: true }).click();
  await expect(nodes).toHaveCount(2);
  await page.getByRole("button", { name: "重置通道", exact: true }).click();
  await expect(nodes).toHaveCount(0);

  await page.getByTestId("hsl-band-blue").click();
  await expect(page.getByTestId("hsl-band-blue")).toHaveAttribute("aria-pressed", "true");
  await commitAdjustment(page, "蓝色 饱和度", "40");
  await expect(
    page.getByRole("slider", { name: "蓝色 饱和度", exact: true }),
  ).toHaveAttribute("aria-valuetext", "+40");
  await page.getByRole("button", { name: "重置当前色带", exact: true }).click();
  await expect(page.getByRole("spinbutton", { name: "蓝色 饱和度", exact: true })).toHaveValue(
    "0",
  );

  await page.getByTestId("grading-zone-midtones").click();
  await commitAdjustment(page, "中间调 色相", "120");
  await commitAdjustment(page, "中间调 强度", "55");
  const swatch = page.getByTestId("grading-swatch-midtones");
  await expect
    .poll(() => swatch.evaluate((element) => getComputedStyle(element).backgroundColor))
    .not.toBe("rgba(0, 0, 0, 0)");
  await page.getByRole("button", { name: "重置当前区域", exact: true }).click();
  await expect
    .poll(() => swatch.evaluate((element) => getComputedStyle(element).backgroundColor))
    .toBe("rgba(0, 0, 0, 0)");

  await page.getByRole("button", { name: "添加矩形区域", exact: true }).click();
  await expect(page.getByText("局部 1 · 矩形", { exact: true })).toBeVisible();
  await expect(page.getByAltText("局部蒙版预览")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("mask-outline")).toBeVisible();

  await commitAdjustment(page, "局部羽化", "40");
  await page.getByRole("slider", { name: "局部羽化", exact: true }).focus();
  await expect(
    page.getByRole("slider", { name: "局部羽化", exact: true }),
  ).toHaveAttribute("aria-valuetext", "+40");

  const widthInput = page.getByRole("spinbutton", { name: "区域宽度（%）", exact: true });
  const beforeMask = await widthInput.inputValue();
  const maskCanvas = page.getByTestId("mask-canvas");
  await maskCanvas.evaluate((element) =>
    element.scrollIntoView({ block: "center", behavior: "instant" }),
  );
  const maskBox = await maskCanvas.boundingBox();
  expect(maskBox, "mask canvas should be laid out").not.toBeNull();
  await drag(
    page,
    { x: maskBox!.x + maskBox!.width * 0.3, y: maskBox!.y + maskBox!.height * 0.3 },
    { x: maskBox!.width * 0.25, y: maskBox!.height * 0.25 },
  );
  await expect(page.getByText("已保存")).toBeVisible();
  expect(await widthInput.inputValue()).not.toBe(beforeMask);

  await page.getByRole("checkbox", { name: "反选蒙版（调整区域外）" }).check();
  await expect(page.getByText(/局部 1 · 矩形 · 反选/)).toBeVisible();

  const modes = page.getByRole("group", { name: "蒙版模式" });
  await modes.getByRole("button", { name: "全图", exact: true }).click();
  await expect(page.getByText("局部 1 · 全图", { exact: true })).toBeVisible();
  await modes.getByRole("button", { name: "矩形", exact: true }).click();
  await expect(page.getByText("局部 1 · 矩形", { exact: true })).toBeVisible();
  await expect(page.getByTestId("mask-canvas")).toBeVisible();

  const anchoredWidth = await widthInput.inputValue();
  await commitAdjustment(page, "旋转", "3");
  await expect(page.getByTestId("mask-canvas")).toBeVisible();
  expect(await widthInput.inputValue()).toBe(anchoredWidth);

  const preview = page.getByAltText("编辑后的预览");
  const beforeLocal = await preview.getAttribute("src");
  await commitAdjustment(page, "局部曝光", "1");
  await expect
    .poll(() => preview.getAttribute("src"), { timeout: 60_000 })
    .not.toBe(beforeLocal);

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1,
  );
  expect(overflow, "page must not scroll horizontally").toBe(false);
});

test("local mask controls remain usable on a phone viewport", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith("mobile"), "mobile interaction coverage");
  await uploadFixture(page);

  await page.getByRole("button", { name: "添加椭圆区域", exact: true }).click();
  await expect(page.getByText("局部 1 · 椭圆", { exact: true })).toBeVisible();
  await expect(page.getByAltText("局部蒙版预览")).toBeVisible({ timeout: 60_000 });

  await commitAdjustment(page, "局部羽化", "35");
  await page.getByRole("checkbox", { name: "反选蒙版（调整区域外）" }).check();
  await expect(page.getByText(/局部 1 · 椭圆 · 反选/)).toBeVisible();
  await expect(page.getByTestId("mask-inner-outline")).toBeVisible();

  const bar = page.getByTestId("mask-canvas");
  await bar.scrollIntoViewIfNeeded();
  const box = await bar.boundingBox();
  expect(box, "mask canvas should be laid out").not.toBeNull();
  expect(box!.width).toBeLessThanOrEqual(390);

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1,
  );
  expect(overflow, "page must not scroll horizontally").toBe(false);
});
