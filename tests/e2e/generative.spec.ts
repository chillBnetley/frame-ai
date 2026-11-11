import { expect, test } from "@playwright/test";

import { openApp, uploadFixture } from "./support";

test("generative creative studio workflow: tabs, outpainting, history attribution and deletion preview", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name.startsWith("mobile"), "desktop interaction coverage");

  await openApp(page);
  await uploadFixture(page);

  // 1. Open AI Creative Studio from main editor
  const openStudioBtn = page.getByRole("button", { name: "AI 创意工作台" });
  await expect(openStudioBtn).toBeVisible({ timeout: 30_000 });
  await openStudioBtn.click();

  // 2. Studio shell rendered with four zones, storage meter, and capability rail
  await expect(page.getByRole("heading", { name: "AI 创意工作台" })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByText("本机 AI 存储预算")).toBeVisible();

  const outpaintTab = page.getByRole("radio", { name: /AI 画幅扩充/ });
  const removeTab = page.getByRole("radio", { name: /AI 智能消除/ });
  const localEditTab = page.getByRole("radio", { name: /AI 局部生成/ });

  await expect(outpaintTab).toBeVisible();
  await expect(removeTab).toBeVisible();
  await expect(localEditTab).toBeVisible();

  // 3. Tab switching works
  await removeTab.click();
  await expect(page.getByText(/请先选择或绘制消除区域蒙版/)).toBeVisible();

  await localEditTab.click();
  await expect(page.getByText(/请填写生成指令/)).toBeVisible();

  // Return to outpaint tab
  await outpaintTab.click();

  // 4. Trigger Outpaint by selecting 1:1 ratio
  const ratio1x1 = page.getByRole("radio", { name: "1:1" });
  await ratio1x1.click();

  const submitBtn = page.getByRole("button", { name: "开始 AI 画幅扩充" });
  await expect(submitBtn).toBeEnabled({ timeout: 10_000 });
  await submitBtn.click();

  // 5. Candidate result arrives and can be accepted
  const acceptBtn = page.getByRole("button", { name: "采纳新画幅并推进版本" });
  await expect(acceptBtn).toBeVisible({ timeout: 60_000 });
  await acceptBtn.click();

  // 6. Verify history bar reflects generative revision
  await expect(page.locator("#creative-studio").getByText(/扩图 · Mock/)).toBeVisible({
    timeout: 30_000,
  });

  // 7. Exit studio and return to main editor view
  const returnBtn = page.getByRole("button", { name: "返回参数精修" });
  await returnBtn.click();
  await expect(page.getByRole("heading", { name: "编辑预览" })).toBeVisible({
    timeout: 30_000,
  });

  // 8. Open Delete Photo dialog and verify deletion breakdown itemizes generative records
  const deleteBtn = page.getByRole("button", { name: "删除照片" });
  await deleteBtn.click();

  await expect(page.getByRole("heading", { name: "删除这张照片？" })).toBeVisible();
  const breakdown = page.getByTestId("deletion-breakdown");
  await expect(breakdown).toBeVisible({ timeout: 15_000 });
  await expect(breakdown).toContainText("将永久清除以下关联记录：");
  await expect(breakdown).toContainText("编辑会话：");
  await expect(breakdown).toContainText("历史版本：");
  await expect(breakdown).toContainText("生成任务：");
  await expect(breakdown).toContainText("生成资产：");

  // Cancel deletion dialog
  await page.getByRole("button", { name: "取消" }).click();
  await expect(page.getByRole("heading", { name: "删除这张照片？" })).toHaveCount(0);
});
