import { expect, test, type Page } from "@playwright/test";

import { openApp, uploadFixture } from "./support";

async function commitAdjustment(page: Page, name: string, value: string): Promise<void> {
  const input = page.getByRole("spinbutton", { name, exact: true });
  await input.fill(value);
  await expect(page.getByText("有未保存的调整")).toBeVisible();
  await input.press("Enter");
  await expect(page.getByText("已保存")).toBeVisible();
}

test("semantic masks follow the capability flag and render a person matte", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name.startsWith("mobile"), "desktop interaction coverage");
  await openApp(page);
  await uploadFixture(page);

  const person = page.getByRole("button", { name: "人物蒙版", exact: true });
  const sky = page.getByRole("button", { name: "天空蒙版（实验性）", exact: true });

  if (process.env.E2E_SEMANTIC_MASKS === "false") {
    await expect(person).toHaveCount(0);
    await expect(sky).toHaveCount(0);
    return;
  }

  await expect(person).toBeEnabled({ timeout: 30_000 });
  await expect(sky).toBeDisabled();
  await expect(sky).toHaveAttribute("title", "天空模型未安装（实验性）");

  const preview = page.getByAltText("编辑后的预览");
  const before = await preview.getAttribute("src");
  await person.click();
  await expect(page.getByText(/局部 1 · 人物（语义）/)).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("已保存")).toBeVisible();

  await commitAdjustment(page, "局部曝光", "0.5");
  await expect
    .poll(() => preview.getAttribute("src"), { timeout: 60_000 })
    .not.toBe(before);
});
