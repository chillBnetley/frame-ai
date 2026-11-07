import { expect, test, type Locator, type Page } from "@playwright/test";
import path from "node:path";

import { ARTIFACTS, analysisFixtureJson, uploadFixture } from "./support";

const PLAN_PATH = "/api/v1/ai/photographer/plan";
const CHAT_PATH = "/api/v1/ai/photographer/chat";

interface Adjustments {
  [key: string]: number | null | undefined;
}

interface Recipe {
  adjustments?: Adjustments;
  curve?: unknown;
  hsl?: unknown;
  colorGrading?: unknown;
  masks?: unknown;
  localAdjustments?: unknown;
  output?: unknown;
}

interface PlanCall {
  planId: string;
  request: Record<string, unknown>;
  recipe: Recipe;
}

interface ChatCall {
  patchId: string;
  planId: string;
  request: Record<string, unknown>;
  supported: boolean;
  changes: Array<{ path: string; previous?: number; proposed?: number }>;
  recipe: Recipe;
  unsupported: string[];
}

interface Recorder {
  plans: PlanCall[];
  chats: ChatCall[];
  revisions: Array<Record<string, unknown>>;
  /** Recipes of revisions the server accepted, in order. */
  saved: Recipe[];
}

/**
 * `/chat` is the contract under test, so the assertions read the request bodies
 * and recipes the server actually returned instead of only the DOM.
 */
function recordChatTraffic(page: Page): Recorder {
  const recorder: Recorder = { plans: [], chats: [], revisions: [], saved: [] };
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
        .then((body: Record<string, unknown>) => {
          recorder.plans.push({
            planId: String(body.planId ?? ""),
            request: JSON.parse(request.postData() ?? "{}") as Record<
              string,
              unknown
            >,
            recipe: (body.recipe ?? {}) as Recipe,
          });
        });
    } else if (pathname === CHAT_PATH) {
      void response
        .json()
        .catch(() => ({}))
        .then((body: Record<string, unknown>) => {
          recorder.chats.push({
            patchId: String(body.patchId ?? ""),
            planId: String(body.planId ?? ""),
            request: JSON.parse(request.postData() ?? "{}") as Record<
              string,
              unknown
            >,
            supported: Boolean(body.supported),
            changes: (body.changes ?? []) as ChatCall["changes"],
            recipe: (body.recipe ?? {}) as Recipe,
            unsupported: (body.unsupported ?? []) as string[],
          });
        });
    } else if (pathname.endsWith("/revisions")) {
      recorder.revisions.push(
        JSON.parse(request.postData() ?? "{}") as Record<string, unknown>,
      );
      void response
        .json()
        .catch(() => ({}))
        .then((body: Record<string, unknown>) => {
          const revision = body.revision as { recipe?: Recipe } | undefined;
          if (revision?.recipe) {
            recorder.saved.push(revision.recipe);
          }
        });
    }
  });
  return recorder;
}

/** Adjustment parameters the recipe moved away from `base`. */
function movedAdjustments(base: Recipe, next: Recipe): Record<string, unknown> {
  const before = base.adjustments ?? {};
  const after = next.adjustments ?? {};
  return Object.fromEntries(
    Object.entries(after).filter(([key, value]) => before[key] !== value),
  );
}

/** Parameters that differ from the untouched default of a brand new session. */
function nonzeroAdjustments(recipe: Recipe): Record<string, number> {
  return Object.fromEntries(
    Object.entries(recipe.adjustments ?? {}).filter(
      ([, value]) => typeof value === "number" && value !== 0,
    ),
  ) as Record<string, number>;
}

/** Everything a chat patch must never touch, compared section by section. */
async function expectSectionsUntouched(
  base: Recipe,
  next: Recipe,
): Promise<void> {
  const sections: Array<keyof Recipe> = [
    "curve",
    "hsl",
    "colorGrading",
    "masks",
    "localAdjustments",
    "output",
  ];
  for (const section of sections) {
    expect(JSON.stringify(next[section]), `${String(section)} moved`).toBe(
      JSON.stringify(base[section]),
    );
  }
  expect(next.adjustments?.crop).toEqual(base.adjustments?.crop);
  expect(next.adjustments?.rotationDeg).toBe(base.adjustments?.rotationDeg);
}

function shot(name: string): string {
  return path.join(ARTIFACTS, `photographer-chat-${name}.png`);
}

function upload(page: Page): Promise<void> {
  return uploadFixture(page, {
    fixtureJson: analysisFixtureJson("desktop-1280x800"),
  });
}

async function openPanel(page: Page): Promise<Locator> {
  await page.getByRole("button", { name: /AI 自动优化/ }).click();
  const panel = page.locator("#photographer-panel");
  await expect(panel.getByRole("heading", { name: "对话调整" })).toBeVisible();
  return panel;
}

async function sendInstruction(
  panel: Locator,
  instruction: string,
): Promise<void> {
  await panel.getByRole("textbox", { name: "调整指令" }).fill(instruction);
  await panel.getByRole("button", { name: "应用这条指令" }).click();
}

/** An accept opens the optional rating dialog; this chain keeps working without a score. */
async function skipRating(page: Page): Promise<void> {
  const rating = page.getByRole("dialog", {
    name: "这次结果的主观评分（可跳过）",
  });
  await expect(rating).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(rating).toHaveCount(0);
}

test("natural-language patch previews, chains, and accepts in the browser", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "desktop-1280x800",
    "the chat composer is verified in the desktop panel layout",
  );
  const recorder = recordChatTraffic(page);

  await page.goto("/");
  await upload(page);
  const panel = await openPanel(page);

  await panel.getByRole("button", { name: "开始自动优化" }).click();
  await expect.poll(() => recorder.plans.length, { timeout: 90_000 }).toBe(1);
  const anchor = recorder.plans[0]!;

  await sendInstruction(panel, "降低饱和度");
  await expect.poll(() => recorder.chats.length, { timeout: 90_000 }).toBe(1);
  const first = recorder.chats[0]!;

  expect(first.request).toMatchObject({
    planId: anchor.planId,
    instruction: "降低饱和度",
  });
  expect(first.supported).toBe(true);
  expect(first.changes).toEqual([
    {
      path: "adjustments.saturation",
      previous: 0,
      proposed: -8,
      reason: expect.any(String),
      evidenceRefs: ["instruction"],
    },
  ]);
  // The unaccepted proposal stays a proposal: only the named parameter moved.
  expect(nonzeroAdjustments(first.recipe)).toEqual({ saturation: -8 });
  await expectSectionsUntouched(anchor.recipe, first.recipe);

  await expect(
    panel.getByRole("heading", { name: "对话调整建议" }),
  ).toBeVisible();
  await expect(panel.getByText("1 项参数变化")).toBeVisible();
  await expect(panel.getByRole("region", { name: "参数变化" })).toContainText(
    "饱和度",
  );
  await page.screenshot({ path: shot("01-patch-preview") });

  // A patch is a preview: nothing is written to history while it is on screen.
  await expect(panel.getByText("有未保存的调整")).toHaveCount(0);
  expect(recorder.revisions).toHaveLength(0);

  await panel.getByRole("button", { name: "原图" }).click();
  await expect(panel.getByRole("button", { name: "原图" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.screenshot({ path: shot("02-original-compare") });

  await panel.getByRole("button", { name: "AI 方案预览" }).click();
  await sendInstruction(panel, "再提高一点对比度");
  await expect.poll(() => recorder.chats.length, { timeout: 90_000 }).toBe(2);
  const second = recorder.chats[1]!;

  // The second turn chains on the first patch, so saturation stays at -8.
  expect(second.planId).toBe(first.patchId);
  expect(nonzeroAdjustments(second.recipe)).toEqual({
    saturation: -8,
    contrast: 10,
  });
  expect(movedAdjustments(first.recipe, second.recipe)).toEqual({
    contrast: 10,
  });
  await expect(panel.getByRole("list", { name: "对话记录" })).toContainText(
    "再提高一点对比度",
  );
  await page.screenshot({ path: shot("03-second-turn") });

  await panel.getByRole("button", { name: "接受方案" }).click();
  await expect
    .poll(() => recorder.saved.length, { timeout: 60_000 })
    .toBe(1);
  expect(recorder.revisions[0]).toMatchObject({ source: "ai" });
  const saved = recorder.saved[0]!;
  expect(saved.adjustments?.saturation).toBe(-8);
  expect(saved.adjustments?.contrast).toBe(10);
  await expect(
    panel.getByRole("heading", { name: "对话调整建议" }),
  ).toHaveCount(0);
  await expect(page.getByText("已保存")).toBeVisible();
  await page.screenshot({ path: shot("04-accepted") });
});

test("an out-of-scope instruction keeps the recipe unchanged", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "desktop-1280x800",
    "the capability boundary note is verified in the desktop panel layout",
  );
  const recorder = recordChatTraffic(page);

  await page.goto("/");
  await upload(page);
  const panel = await openPanel(page);

  await panel.getByRole("button", { name: "开始自动优化" }).click();
  await expect.poll(() => recorder.plans.length, { timeout: 90_000 }).toBe(1);
  await panel.getByRole("button", { name: "接受方案" }).click();
  await expect.poll(() => recorder.saved.length, { timeout: 60_000 }).toBe(1);
  await skipRating(page);
  const accepted = recorder.saved[0]!;

  await sendInstruction(panel, "删除背景里的人物");
  await expect.poll(() => recorder.chats.length, { timeout: 90_000 }).toBe(1);
  const rejected = recorder.chats[0]!;

  expect(rejected.supported).toBe(false);
  expect(rejected.changes).toHaveLength(0);
  expect(rejected.unsupported.length).toBeGreaterThan(0);
  expect(movedAdjustments(accepted, rejected.recipe)).toEqual({});
  await expectSectionsUntouched(accepted, rejected.recipe);

  await expect(
    panel.getByRole("heading", { name: "这项调整不支持" }),
  ).toBeVisible();
  await expect(panel.getByText("配方未变化", { exact: true })).toBeVisible();
  await expect(
    panel.getByText("当前配方未发生变化，画面保持你已有的调整。"),
  ).toBeVisible();
  await expect(panel.getByRole("button", { name: "接受方案" })).toBeDisabled();
  await page.screenshot({ path: shot("05-unsupported") });

  await panel.getByRole("button", { name: "放弃" }).click();
  await expect(
    panel.getByRole("heading", { name: "这项调整不支持" }),
  ).toHaveCount(0);
  expect(recorder.revisions).toHaveLength(1);
});

test("a saved manual edit survives a chat patch", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "desktop-1280x800",
    "the non-destructive guarantee is verified in the desktop panel layout",
  );
  const recorder = recordChatTraffic(page);

  await page.goto("/");
  await upload(page);

  const temperature = page.getByRole("spinbutton", {
    name: "色温",
    exact: true,
  });
  await temperature.fill("20");
  await expect(page.getByText("有未保存的调整")).toBeVisible();
  await temperature.press("Enter");
  await expect(page.getByText("已保存")).toBeVisible();
  await expect(page.getByRole("button", { name: /#2 · 手动/ })).toBeVisible({
    timeout: 60_000,
  });
  await expect.poll(() => recorder.saved.length, { timeout: 60_000 }).toBe(1);
  const mine = recorder.saved[0]!;
  expect(mine.adjustments?.temperature).toBe(20);

  const panel = await openPanel(page);
  // The composer anchors on this analysis, whose plan starts from the saved edit.
  await panel.getByRole("button", { name: "开始自动优化" }).click();
  await expect.poll(() => recorder.plans.length, { timeout: 90_000 }).toBe(1);
  await sendInstruction(panel, "降低饱和度");
  await expect.poll(() => recorder.chats.length, { timeout: 90_000 }).toBe(1);
  const patch = recorder.chats[0]!;

  expect(patch.request.planId).toBe(recorder.plans[0]!.planId);
  expect(patch.changes.map((change) => change.path)).toEqual([
    "adjustments.saturation",
  ]);
  expect(movedAdjustments(mine, patch.recipe)).toEqual({ saturation: -8 });
  expect(patch.recipe.adjustments?.temperature).toBe(20);
  await expectSectionsUntouched(mine, patch.recipe);
  await page.screenshot({ path: shot("06-after-manual-edit") });

  await panel.getByRole("button", { name: "接受方案" }).click();
  await expect.poll(() => recorder.saved.length, { timeout: 60_000 }).toBe(2);
  expect(recorder.revisions[1]).toMatchObject({ source: "ai" });
  const after = recorder.saved[1]!;
  expect(after.adjustments?.temperature).toBe(20);
  expect(after.adjustments?.saturation).toBe(-8);
  await expect(page.getByRole("button", { name: /#3 · AI/ })).toBeVisible({
    timeout: 60_000,
  });
});
