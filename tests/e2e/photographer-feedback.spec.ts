import { expect, test, type Locator, type Page } from "@playwright/test";
import path from "node:path";

import { ARTIFACTS, analysisFixtureJson, uploadFixture } from "./support";

const PLAN_PATH = "/api/v1/ai/photographer/plan";
const FEEDBACK_PATH = "/api/v1/ai/photographer/feedback";
const RATING_TITLE = "这次结果的主观评分（可跳过）";

interface FeedbackBody {
  sessionId?: string;
  action?: string;
  source?: string;
  planId?: string;
  revisionId?: string;
  rubric?: Record<string, number>;
}

interface FeedbackRecord {
  id: string;
  action: string;
  planId: string | null;
  revisionId: string | null;
  changedPaths: string[];
  rubric: Record<string, number> | null;
  isMock: boolean;
  degraded: boolean;
}

interface Recorder {
  planIds: string[];
  posts: FeedbackBody[];
  stored: FeedbackRecord[];
  listTotals: number[];
  deletes: string[];
  revisions: number;
  resets: number;
}

/**
 * Feedback is a write-then-read contract, so the assertions read the bodies the
 * server returned instead of only the DOM the client rendered.
 */
function recordTraffic(page: Page): Recorder {
  const recorder: Recorder = {
    planIds: [],
    posts: [],
    stored: [],
    listTotals: [],
    deletes: [],
    revisions: 0,
    resets: 0,
  };
  page.on("response", (response) => {
    const request = response.request();
    const pathname = new URL(response.url()).pathname;
    const method = request.method();

    if (method === "POST" && pathname === PLAN_PATH) {
      void response
        .json()
        .catch(() => ({}))
        .then((body: { planId?: string }) => {
          if (body.planId) {
            recorder.planIds.push(body.planId);
          }
        });
      return;
    }
    if (method === "POST" && pathname.endsWith("/revisions")) {
      recorder.revisions += 1;
      return;
    }
    if (method === "POST" && pathname.endsWith("/reset")) {
      recorder.resets += 1;
      return;
    }
    if (method === "POST" && pathname === FEEDBACK_PATH) {
      recorder.posts.push(JSON.parse(request.postData() ?? "{}") as FeedbackBody);
      void response
        .json()
        .catch(() => null)
        .then((body: FeedbackRecord | null) => {
          if (body) {
            recorder.stored.push(body);
          }
        });
      return;
    }
    if (method === "GET" && pathname === FEEDBACK_PATH) {
      void response
        .json()
        .catch(() => null)
        .then((body: { summary?: { total?: number } } | null) => {
          if (body?.summary && typeof body.summary.total === "number") {
            recorder.listTotals.push(body.summary.total);
          }
        });
      return;
    }
    if (method === "DELETE" && pathname.startsWith(`${FEEDBACK_PATH}/`)) {
      recorder.deletes.push(pathname.slice(FEEDBACK_PATH.length + 1));
    }
  });
  return recorder;
}

function shot(name: string): string {
  return path.join(ARTIFACTS, `photographer-feedback-${name}.png`);
}

function upload(page: Page, project: string): Promise<void> {
  return uploadFixture(page, { fixtureJson: analysisFixtureJson(project) });
}

async function openPanel(page: Page): Promise<Locator> {
  await page.getByRole("button", { name: /AI 自动优化/ }).click();
  const panel = page.locator("#photographer-panel");
  await expect(
    panel.getByRole("button", { name: "开始自动优化" }),
  ).toBeVisible();
  return panel;
}

async function plan(page: Page, panel: Locator): Promise<void> {
  await panel.getByRole("button", { name: "开始自动优化" }).click();
  await expect(panel.getByRole("button", { name: "接受方案" })).toBeEnabled({
    timeout: 90_000,
  });
}

function section(page: Page): Locator {
  return page.getByRole("region", { name: "反馈与评分" });
}

function dialog(page: Page): Locator {
  return page.getByRole("dialog", { name: RATING_TITLE });
}

async function refresh(page: Page): Promise<void> {
  const button = section(page).getByRole("button", { name: "刷新" });
  // The refresh button is disabled while a read is still open, so wait it out
  // before treating the next response as ours.
  await expect(button).toBeEnabled();
  const refreshed = page.waitForResponse(
    (response) =>
      response.request().method() === "GET" &&
      new URL(response.url()).pathname === FEEDBACK_PATH &&
      response.status() === 200,
  );
  await button.click();
  await refreshed;
}

test("accepting a plan records the decision, then the optional 1–5 rubric", async (
  { page },
  testInfo,
) => {
  test.skip(
    testInfo.project.name !== "desktop-1280x800",
    "the feedback flow is verified in the desktop layout",
  );
  const recorder = recordTraffic(page);

  await page.goto("/");
  await upload(page, testInfo.project.name);
  const panel = await openPanel(page);

  // Before any decision the section says so, and it never promises a verdict.
  await expect(
    section(page).getByText(
      "还没有反馈记录。接受或放弃方案时会自动记录，你可以随时删除。",
    ),
  ).toBeVisible();

  await plan(page, panel);
  await panel.getByRole("button", { name: "接受方案" }).click();
  await expect
    .poll(() => recorder.posts.length, { timeout: 60_000 })
    .toBe(1);

  // The recorded anchor is the real one: this session, this plan, this revision.
  expect(recorder.posts[0]).toEqual({
    sessionId: expect.any(String),
    action: "accepted",
    source: "plan",
    planId: recorder.planIds[0],
    revisionId: expect.any(String),
  });
  await expect
    .poll(() => recorder.stored.length, { timeout: 60_000 })
    .toBe(1);
  const accepted = recorder.stored[0]!;
  expect(accepted.action).toBe("accepted");
  expect(accepted.isMock).toBe(true);
  expect(accepted.degraded).toBe(false);
  expect(accepted.rubric).toBeNull();
  // A clean acceptance changed nothing beyond what the plan already proposed,
  // so there is nothing to report as a later user edit.
  expect(accepted.changedPaths).toEqual([]);

  // The rubric is optional and covers exactly the ten documented dimensions.
  await expect(dialog(page)).toBeVisible();
  // The dialog is portalled to <body>. A backdrop-filter ancestor would become
  // its containing block and push it off screen while toBeVisible still passes.
  const viewport = page.viewportSize()!;
  const ratingBox = (await dialog(page).boundingBox())!;
  expect(ratingBox.x).toBeGreaterThanOrEqual(0);
  expect(ratingBox.y).toBeGreaterThanOrEqual(0);
  expect(ratingBox.x + ratingBox.width).toBeLessThanOrEqual(viewport.width);
  expect(ratingBox.y + ratingBox.height).toBeLessThanOrEqual(viewport.height);
  await expect(
    dialog(page).getByText(
      "接受、拒绝与评分只是主观偏好记录，不代表方案在客观质量上更优。",
    ),
  ).toBeVisible();
  await expect(dialog(page).getByRole("radiogroup")).toHaveCount(10);
  await expect(dialog(page).getByRole("radio")).toHaveCount(50);
  await expect(
    dialog(page).getByRole("button", { name: "保存评分（0/10）" }),
  ).toBeDisabled();

  await dialog(page).getByRole("radio", { name: "曝光 较好" }).click();
  await dialog(page).getByRole("radio", { name: "高光 很好" }).click();
  await dialog(page).getByRole("radio", { name: "肤色 偏差" }).click();
  await expect(
    dialog(page).getByRole("button", { name: "保存评分（3/10）" }),
  ).toBeEnabled();
  await page.screenshot({ path: shot("01-rating") });
  await dialog(page).getByRole("button", { name: "保存评分（3/10）" }).click();

  await expect
    .poll(() => recorder.posts.length, { timeout: 60_000 })
    .toBe(2);
  expect(recorder.posts[1]).toEqual({
    sessionId: expect.any(String),
    action: "accepted",
    source: "plan",
    planId: recorder.planIds[0],
    revisionId: accepted.revisionId,
    rubric: { exposure: 4, highlights: 5, skinTone: 2 },
  });
  await expect(dialog(page)).toHaveCount(0);
  await expect
    .poll(() => recorder.stored.length, { timeout: 60_000 })
    .toBe(2);
  // The same (planId, action) row is annotated, not duplicated.
  expect(recorder.stored[1]!.id).toBe(accepted.id);

  await refresh(page);
  const row = section(page)
    .locator("li")
    .filter({ hasText: "已接受 · 摄影方案" });
  await expect(row).toHaveCount(1);
  await expect(row.getByText("模拟方案", { exact: true })).toBeVisible();
  for (const chip of ["曝光 4", "高光 5", "肤色 2"]) {
    await expect(row.getByText(chip, { exact: true })).toBeVisible();
  }
  await page.screenshot({ path: shot("02-recorded") });

  // Behaviour counts, never a quality verdict.
  for (const chip of [
    "接受 1",
    "接受后调整 0",
    "拒绝 0",
    "重置 0",
    "已评分 1",
    "模拟 1",
    "真实 0",
  ]) {
    await expect(section(page).getByText(chip, { exact: true })).toBeVisible();
  }
  await expect(
    section(page).getByText(
      "接受、拒绝、修改与重置只记录用户行为，不代表方案在客观质量上更优。",
    ),
  ).toBeVisible();
  await expect(
    section(page).getByText(
      "反馈只记录操作、参数路径与分数，不保存照片、指令原文或任何文字备注。",
    ),
  ).toBeVisible();
  await expect(section(page).getByText(/质量提升/)).toHaveCount(0);
  await expect(section(page).getByText(/更好/)).toHaveCount(0);

  // Resetting is recorded with the parameters the reset moved.
  await page.getByRole("button", { name: "重置", exact: true }).click();
  await expect
    .poll(() => recorder.posts.length, { timeout: 60_000 })
    .toBe(3);
  expect(recorder.posts[2]).toEqual({
    sessionId: expect.any(String),
    action: "reset",
    revisionId: expect.any(String),
  });
  await expect
    .poll(() => recorder.stored.length, { timeout: 60_000 })
    .toBe(3);
  const reset = recorder.stored[2]!;
  expect(reset.action).toBe("reset");
  expect(reset.planId).toBeNull();
  expect(reset.changedPaths.length).toBeGreaterThan(0);

  await refresh(page);
  const resetRow = section(page).locator("li").filter({ hasText: "已重置" });
  await expect(resetRow).toHaveCount(1);
  await expect(resetRow.locator("p").filter({ hasText: "改动：" })).toBeVisible();
  await expect(
    section(page).locator("p").filter({ hasText: "最常改动的参数：" }),
  ).toBeVisible();

  // One record is removable without touching the others.
  const before = await section(page).locator("li").count();
  await resetRow.getByRole("button", { name: "删除这条反馈记录" }).click();
  await expect.poll(() => recorder.deletes.length, { timeout: 60_000 }).toBe(1);
  expect(recorder.deletes[0]).toBe(reset.id);
  await expect
    .poll(() => section(page).locator("li").count(), { timeout: 60_000 })
    .toBe(before - 1);
  await expect(
    section(page).locator("li").filter({ hasText: "已接受 · 摄影方案" }),
  ).toHaveCount(1);
  // The accept commits a revision; the reset is its own endpoint. Each decision
  // anchors to the revision it describes, so the two rows never share one.
  expect(recorder.revisions).toBe(1);
  expect(recorder.resets).toBe(1);
  expect(reset.revisionId).not.toBeNull();
  expect(reset.revisionId).not.toBe(accepted.revisionId);
});

test("a rejected proposal, a failed send and its retry stay honest", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "desktop-1280x800",
    "the retry flow is verified in the desktop layout",
  );
  const recorder = recordTraffic(page);
  let blockPosts = false;
  await page.route(
    (url) => new URL(url.toString()).pathname === FEEDBACK_PATH,
    (route) => {
      if (route.request().method() === "POST" && blockPosts) {
        void route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ code: "storage_error" }),
        });
        return;
      }
      void route.continue();
    },
  );

  await page.goto("/");
  await upload(page, testInfo.project.name);
  const panel = await openPanel(page);

  await plan(page, panel);
  await panel.getByRole("button", { name: "放弃" }).click();
  await expect
    .poll(() => recorder.posts.length, { timeout: 60_000 })
    .toBe(1);

  // A rejection carries no revision and stores no prose.
  expect(recorder.posts[0]).toEqual({
    sessionId: expect.any(String),
    action: "rejected",
    source: "plan",
    planId: recorder.planIds[0],
  });
  expect(recorder.posts[0]).not.toHaveProperty("revisionId");
  expect(recorder.posts[0]).not.toHaveProperty("rubric");
  await expect
    .poll(() => recorder.stored.length, { timeout: 60_000 })
    .toBe(1);
  expect(recorder.stored[0]!.changedPaths).toEqual([]);
  expect(recorder.revisions).toBe(0);

  await refresh(page);
  await expect(
    section(page)
      .locator("li")
      .filter({ hasText: "已拒绝 · 摄影方案" }),
  ).toHaveCount(1);

  // A failing feedback write must not block editing: the decision is queued.
  blockPosts = true;
  await plan(page, panel);
  await panel.getByRole("button", { name: "接受方案" }).click();
  await expect
    .poll(() => recorder.posts.length, { timeout: 60_000 })
    .toBe(2);
  await expect(
    section(page).getByRole("button", { name: /1 条待重发 · 重试/ }),
  ).toBeVisible();
  await expect(
    section(page).getByRole("alert").filter({ hasText: "反馈未能保存" }),
  ).toBeVisible();
  // No score dialog for a decision the server never confirmed.
  await expect(dialog(page)).toHaveCount(0);
  // The photo edit itself is unaffected and still lands.
  expect(recorder.revisions).toBe(1);
  await page.screenshot({ path: shot("03-queued") });

  blockPosts = false;
  await section(page)
    .getByRole("button", { name: /1 条待重发 · 重试/ })
    .click();
  await expect
    .poll(() => section(page).locator("li").count(), { timeout: 60_000 })
    .toBe(2);
  await expect(
    section(page).getByRole("button", { name: /条待重发/ }),
  ).toHaveCount(0);
  await expect
    .poll(() => recorder.listTotals.at(-1), { timeout: 60_000 })
    .toBe(2);

  expect(recorder.posts[1]).toEqual({
    sessionId: expect.any(String),
    action: "accepted",
    source: "plan",
    planId: recorder.planIds[1],
    revisionId: expect.any(String),
  });
  await page.screenshot({ path: shot("04-retried") });
});
