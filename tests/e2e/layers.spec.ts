import { expect, test, type Page } from "@playwright/test";

import { openApp, uploadFixture } from "./support";

async function saved(page: Page): Promise<void> {
  await expect(page.getByText("已保存")).toBeVisible({ timeout: 60_000 });
}

function layerRows(page: Page) {
  return page.locator('[data-testid^="layer-row-"]');
}

async function layerIds(page: Page): Promise<(string | null)[]> {
  return layerRows(page).evaluateAll((rows) =>
    rows.map((row) => row.getAttribute("data-testid")),
  );
}

test("layers reorder, hide, blend, fade, delete and undo", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name.startsWith("mobile"), "desktop interaction coverage");
  await openApp(page);
  await uploadFixture(page);

  await page.getByRole("button", { name: "添加全图局部调整", exact: true }).click();
  await expect(page.getByText("局部 1 · 全图", { exact: true })).toBeVisible();
  await saved(page);

  await page.getByRole("button", { name: "添加全图局部调整", exact: true }).click();
  await expect(page.getByText("局部 2 · 全图", { exact: true })).toBeVisible();
  await saved(page);
  await expect(layerRows(page)).toHaveCount(2);

  const originalOrder = await layerIds(page);
  await page.getByRole("button", { name: "上移图层 2", exact: true }).click();
  await expect
    .poll(() => layerIds(page), { timeout: 30_000 })
    .toEqual([originalOrder[1], originalOrder[0]]);
  await saved(page);

  await page.getByRole("button", { name: "撤销", exact: true }).click();
  await expect
    .poll(() => layerIds(page), { timeout: 30_000 })
    .toEqual(originalOrder);
  await saved(page);

  await page.getByRole("button", { name: "上移图层 2", exact: true }).click();
  await expect
    .poll(() => layerIds(page), { timeout: 30_000 })
    .toEqual([originalOrder[1], originalOrder[0]]);
  await saved(page);

  await page.getByRole("checkbox", { name: "启用局部 1", exact: true }).uncheck();
  await expect(page.getByText(/局部 1 · 全图 · 已停用/)).toBeVisible();
  await saved(page);

  await page.getByRole("combobox", { name: "混合模式 1", exact: true }).selectOption("multiply");
  await expect(page.getByRole("combobox", { name: "混合模式 1", exact: true })).toHaveValue(
    "multiply",
  );
  await saved(page);

  const opacity = page.getByRole("spinbutton", { name: "图层不透明度", exact: true });
  await opacity.fill("40");
  await expect(page.getByText("有未保存的调整")).toBeVisible();
  await opacity.press("Enter");
  await saved(page);

  await page.getByRole("button", { name: "删除局部 2", exact: true }).click();
  await expect(layerRows(page)).toHaveCount(1);
  await saved(page);

  await page.getByRole("button", { name: "撤销", exact: true }).click();
  await expect(layerRows(page)).toHaveCount(2);
  await saved(page);
});
