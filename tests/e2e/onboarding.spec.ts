import fs from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

const DATA_DIR = process.env.E2E_DATA_DIR?.trim();
const MARKER_PATH = DATA_DIR ? path.join(DATA_DIR, "onboarding.json") : null;

function markCompleted(): void {
  if (!MARKER_PATH) {
    return;
  }
  fs.mkdirSync(path.dirname(MARKER_PATH), { recursive: true });
  fs.writeFileSync(
    MARKER_PATH,
    `${JSON.stringify(
      {
        version: 1,
        completed: true,
        completedAt: new Date().toISOString(),
      },
      null,
      2,
    )}\n`,
    "utf8",
  );
}

test.describe("首次启动引导", () => {
  test.skip(MARKER_PATH === null, "需要在隔离的 E2E_DATA_DIR 下运行");
  test.use({ reducedMotion: "no-preference" });

  test.beforeEach(() => {
    fs.rmSync(MARKER_PATH!, { force: true });
  });

  test.afterEach(() => {
    markCompleted();
  });

  test("开场 → 结束页 → 照片工作台", async ({ page }) => {
    await page.goto("/");

    await expect(page).toHaveURL(/\/welcome$/);
    await expect(
      page.getByRole("heading", { name: "私人 AI 摄影大师" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "开始你的摄影之旅" }),
    ).toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: "开始" }).click();

    await expect(
      page.getByRole("heading", { name: "照片工作台" }),
    ).toBeVisible();
    await expect(page).not.toHaveURL(/\/welcome$/);
    expect(fs.existsSync(MARKER_PATH!)).toBe(true);
  });

  test("已有完成标记时直接进入照片工作台", async ({ page }) => {
    markCompleted();

    await page.goto("/");

    await expect(
      page.getByRole("heading", { name: "照片工作台" }),
    ).toBeVisible();
    await expect(page).not.toHaveURL(/\/welcome$/);
  });
});
