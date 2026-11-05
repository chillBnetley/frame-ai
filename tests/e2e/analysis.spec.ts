import {
  expect,
  test,
  type APIRequestContext,
  type Page,
  type TestInfo,
} from "@playwright/test";
import fs from "node:fs";

import { analysisFixtureJson } from "./support";

interface Fixture {
  path: string;
  sha256: string;
  width: number;
  height: number;
  bytes: number;
}

const API_URL =
  process.env.E2E_API_URL ??
  `http://127.0.0.1:${process.env.E2E_API_PORT ?? 8010}`;

function fixtureFor(testInfo: TestInfo): Fixture {
  return JSON.parse(
    fs.readFileSync(analysisFixtureJson(testInfo.project.name), "utf8"),
  ) as Fixture;
}

async function upload(page: Page, fixture: Fixture, inputTestId: string): Promise<void> {
  const uploaded = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/v1/images" &&
      response.status() === 201,
  );
  if (inputTestId === "file-input") {
    await page.getByTestId(inputTestId).setInputFiles(fixture.path);
  } else {
    await page.locator(`input[aria-label="${inputTestId}"]`).setInputFiles(fixture.path);
  }
  await uploaded;
  await expect(page.getByRole("heading", { name: "编辑预览" })).toBeVisible();
}

async function waitForTask(
  request: APIRequestContext,
  analysisId: string,
): Promise<Record<string, unknown>> {
  let body: Record<string, unknown> = {};
  await expect
    .poll(
      async () => {
        const response = await request.get(`${API_URL}/api/v1/analysis/${analysisId}`);
        if (!response.ok()) {
          return `http_${response.status()}`;
        }
        body = (await response.json()) as Record<string, unknown>;
        return body.status;
      },
      { timeout: 90_000, intervals: [250, 500, 1_000] },
    )
    .toBe("completed");
  return body;
}

test("analysis retry, report sections, rerun, and image switch", async ({
  page,
  request,
}, testInfo) => {
  const fixture = fixtureFor(testInfo);
  await page.goto("/");
  await upload(page, fixture, "file-input");
  await expect(page.getByAltText("编辑后的预览")).toBeVisible({ timeout: 60_000 });

  await page.getByRole("button", { name: "AI 摄影分析", exact: true }).click();
  const panel = page.locator("#analysis-panel");
  await expect(panel).toBeVisible();

  let intercepted = false;
  await page.route("**/api/v1/analysis", async (route) => {
    if (route.request().method() !== "POST" || intercepted) {
      await route.continue();
      return;
    }
    intercepted = true;
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      headers: { "X-Request-ID": "e2e-analysis-failure" },
      body: JSON.stringify({
        error: {
          code: "analysis_unavailable",
          message: "模拟分析服务不可用",
          details: {},
        },
      }),
    });
  });

  await page.getByRole("button", { name: "开始分析", exact: true }).click();
  const alert = panel.getByRole("alert");
  await expect(alert).toContainText("模拟分析服务不可用");
  await expect(alert).toContainText("analysis_unavailable");
  await expect(page.getByText("分析失败", { exact: true })).toBeVisible();

  const retryResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/v1/analysis" &&
      response.status() === 202,
  );
  await page.getByRole("button", { name: "重试", exact: true }).click();
  const created = (await (await retryResponse).json()) as {
    analysisId: string;
    status: string;
  };
  const completed = await waitForTask(request, created.analysisId);
  expect(completed.status).toBe("completed");

  await expect(page.getByText("分析完成", { exact: true })).toBeVisible();
  await expect(
    page.getByText("模拟分析（未调用真实视觉模型）", { exact: true }),
  ).toBeVisible();

  for (const name of [
    "场景识别",
    "主体识别",
    "光线与色彩",
    "摄影问题",
    "AI 摄影建议",
    "局限与说明",
  ]) {
    const region = page.getByRole("region", { name });
    await expect(region).toBeVisible();
    await expect(region.getByRole("heading", { name })).toBeVisible();
  }

  await expect(
    page.getByText("· 模拟数据：未调用真实视觉模型。", { exact: true }),
  ).toBeVisible();
  const subjectRegion = page.getByRole("region", { name: "主体识别" });
  await expect(subjectRegion).toContainText("人物");
  await expect(
    subjectRegion.getByRole("heading", { name: "构图与遮挡" }),
  ).toBeVisible();
  await expect(subjectRegion).toContainText("构图平衡");
  await expect(subjectRegion).toContainText("遮挡");

  await subjectRegion.getByRole("button", { name: "显示主体框" }).click();
  await expect(page.getByAltText("原图主体框叠加预览")).toBeVisible();
  await subjectRegion.getByRole("button", { name: "隐藏主体框" }).click();
  await expect(page.getByAltText("原图主体框叠加预览")).toHaveCount(0);

  const rerunRequest = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      new URL(request.url()).pathname === "/api/v1/analysis",
  );
  const rerunResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/v1/analysis" &&
      response.status() === 202,
  );
  await page.getByRole("button", { name: "重新分析", exact: true }).click();
  expect((await rerunRequest).postDataJSON()).toMatchObject({ force: true });
  const rerun = (await (await rerunResponse).json()) as { analysisId: string };
  expect(rerun.analysisId).not.toBe(created.analysisId);
  await waitForTask(request, rerun.analysisId);
  await expect(page.getByText("分析完成", { exact: true })).toBeVisible();

  await upload(page, fixture, "更换照片");
  await expect(panel).toHaveCount(0);
  await page.getByRole("button", { name: "AI 摄影分析", exact: true }).click();
  await expect(page.getByRole("button", { name: "开始分析", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "场景识别" })).toHaveCount(0);

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1,
  );
  expect(overflow, "page must not scroll horizontally").toBe(false);
});