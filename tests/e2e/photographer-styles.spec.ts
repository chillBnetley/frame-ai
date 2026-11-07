import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

import { ARTIFACTS, analysisFixtureJson, uploadFixture } from "./support";

const PLAN_PATH = "/api/v1/ai/photographer/plan";

interface Adjustments {
  saturation?: number;
  contrast?: number;
}

interface PlanCall {
  request: Record<string, unknown>;
  response: Record<string, unknown>;
}

interface Recorder {
  plans: PlanCall[];
  revisions: Array<Record<string, unknown>>;
}

function recipeOf(call: PlanCall | undefined): {
  adjustments?: Adjustments;
  styleId?: string;
  styleStrength?: number;
} {
  return (call?.response.recipe ?? {}) as ReturnType<typeof recipeOf>;
}

/**
 * The plan endpoint is the contract under test, so the assertions read the real
 * request bodies and recipes the server returned instead of only the DOM.
 */
function recordPhotographerTraffic(page: Page): Recorder {
  const recorder: Recorder = { plans: [], revisions: [] };
  page.on("response", (response) => {
    const request = response.request();
    if (request.method() !== "POST") {
      return;
    }
    const pathname = new URL(response.url()).pathname;
    if (pathname === PLAN_PATH) {
      void response
        .json()
        .catch(() => ({}))
        .then((body: unknown) => {
          recorder.plans.push({
            request: JSON.parse(request.postData() ?? "{}") as Record<string, unknown>,
            response: body as Record<string, unknown>,
          });
        });
    } else if (pathname.endsWith("/revisions")) {
      recorder.revisions.push(
        JSON.parse(request.postData() ?? "{}") as Record<string, unknown>,
      );
    }
  });
  return recorder;
}

function shot(name: string): string {
  return path.join(ARTIFACTS, `photographer-styles-${name}.png`);
}

/**
 * Largest R/G/B spread sampled from the rendered preview, or -1 while the image
 * has not loaded. Grayscale styles must drive this to ~0 in the browser, which
 * is the only proof that the style reached the render engine.
 */
async function maxChannelDiff(page: Page): Promise<number> {
  return page.evaluate(() => {
    const img = document.querySelector(
      'img[alt="编辑后的预览"]',
    ) as HTMLImageElement | null;
    if (img === null || !img.complete || img.naturalWidth === 0) {
      return -1;
    }
    const canvas = document.createElement("canvas");
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    const context = canvas.getContext("2d");
    if (context === null) {
      return -1;
    }
    context.drawImage(img, 0, 0);
    const { data } = context.getImageData(0, 0, canvas.width, canvas.height);
    let diff = 0;
    for (let offset = 0; offset < data.length; offset += 4) {
      const r = data[offset] ?? 0;
      const g = data[offset + 1] ?? 0;
      const b = data[offset + 2] ?? 0;
      diff = Math.max(diff, Math.abs(r - g), Math.abs(g - b), Math.abs(r - b));
    }
    return diff;
  });
}

async function expectGrayscale(page: Page): Promise<void> {
  await expect
    .poll(async () => {
      const diff = await maxChannelDiff(page);
      return diff >= 0 && diff <= 4;
    })
    .toBe(true);
}


test("style catalog, strength blending and accepted recipe in the browser", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "desktop-1280x800",
    "the style picker is verified in the desktop panel layout",
  );
  const recorder = recordPhotographerTraffic(page);

  await page.goto("/");
  await uploadFixture(page, {
    fixtureJson: analysisFixtureJson(testInfo.project.name),
  });
  await expect(page.getByAltText("编辑后的预览")).toBeVisible({ timeout: 60_000 });

  await page.getByRole("button", { name: /AI 自动优化/ }).click();
  const panel = page.locator("#photographer-panel");
  await expect(
    panel.getByRole("heading", { name: "摄影风格" }),
  ).toBeVisible();

  const autoChip = panel.getByRole("button", { name: "自动优化（不选风格）" });
  await expect(autoChip).toHaveAttribute("aria-pressed", "true");
  await expect(panel.getByRole("button", { name: "黑白纪实" })).toBeVisible();
  await expect(panel.getByRole("button", { name: "电影叙事" })).toBeVisible();
  await page.screenshot({ path: shot("01-catalog") });

  await panel.getByRole("button", { name: "开始自动优化" }).click();
  await expect
    .poll(() => recorder.plans.length, { timeout: 90_000 })
    .toBe(1);
  expect(recorder.plans[0]?.request).toMatchObject({ mode: "auto" });
  await expect(panel.getByText("方案已就绪")).toBeVisible();
  await expect
    .poll(async () => (await maxChannelDiff(page)) > 12)
    .toBe(true);

  await panel.getByRole("button", { name: "黑白纪实" }).click();
  await expect.poll(() => recorder.plans.length).toBe(2);
  expect(recorder.plans[1]?.request).toMatchObject({
    mode: "style",
    styleId: "monochrome",
    styleStrength: 0.7,
  });
  expect(recipeOf(recorder.plans[1]).adjustments?.saturation).toBe(-100);
  expect(recipeOf(recorder.plans[1]).styleId).toBe("documentary");
  expect(recipeOf(recorder.plans[1]).styleStrength ?? 0).toBeCloseTo(70, 1);
  await expect(
    panel.getByText(/风格 monochrome v1\.0 · 强度 70%/),
  ).toBeVisible();
  await expect(
    panel.getByText(/风格由参数组合实时计算，不依赖 LUT/),
  ).toBeVisible();
  await expectGrayscale(page);
  await page.screenshot({ path: shot("02-monochrome") });

  const slider = panel.getByRole("slider", { name: "风格强度" });
  // `press` re-focuses: the slider is disabled while a plan is in flight, which
  // drops focus after the previous keystroke.
  await slider.press("Home");
  await expect.poll(() => recorder.plans.length).toBe(3);
  expect(recorder.plans[2]?.request).toMatchObject({
    mode: "style",
    styleId: "monochrome",
    styleStrength: 0,
  });
  expect(recipeOf(recorder.plans[2]).adjustments?.saturation ?? 0).toBeGreaterThan(-100);
  await expect(
    panel.getByText(/强度 0 时不叠加任何风格参数/),
  ).toBeVisible();
  await expect
    .poll(async () => (await maxChannelDiff(page)) > 12)
    .toBe(true);
  await page.screenshot({ path: shot("03-strength-0") });

  await slider.press("End");
  await expect.poll(() => recorder.plans.length).toBe(4);
  expect(recorder.plans[3]?.request).toMatchObject({ styleStrength: 1 });
  expect(recipeOf(recorder.plans[3]).adjustments?.saturation).toBe(-100);
  await expect(panel.getByRole("slider", { name: "风格强度" })).toHaveAttribute(
    "aria-valuetext",
    "100%",
  );
  await expectGrayscale(page);
  await page.screenshot({ path: shot("04-strength-100") });

  // Switching style or strength only ever produces a proposal.
  expect(recorder.revisions).toHaveLength(0);

  await panel.getByRole("button", { name: "接受方案" }).click();
  await expect.poll(() => recorder.revisions.length).toBe(1);
  expect(recorder.revisions[0]).toMatchObject({ source: "ai" });
  const savedRecipe = recorder.revisions[0]?.recipe as
    | { adjustments?: Adjustments }
    | undefined;
  expect(savedRecipe?.adjustments?.saturation).toBe(-100);
  await expectGrayscale(page);
  await page.screenshot({ path: shot("05-accepted") });
});
