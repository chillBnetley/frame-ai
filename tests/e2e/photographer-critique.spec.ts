import { expect, test, type Locator, type Page } from "@playwright/test";
import path from "node:path";

import { ARTIFACTS, analysisFixtureJson, uploadFixture } from "./support";

const PLAN_PATH = "/api/v1/ai/photographer/plan";
const CRITIQUE_PATH = "/api/v1/ai/photographer/critique";
const APPLY_PATH = "/api/v1/ai/photographer/critique/apply";

interface Point {
  text: string;
  evidenceRefs: string[];
  subjective?: boolean;
  category?: string;
  recipePatch?: Record<string, number | null> | null;
}

interface Recipe {
  adjustments?: Record<string, number | null | undefined>;
  curve?: unknown;
  hsl?: unknown;
  colorGrading?: unknown;
  masks?: unknown;
  localAdjustments?: unknown;
  output?: unknown;
}

interface Critique {
  analysisId: string;
  isMock: boolean;
  generatedBy: string;
  strengths: Point[];
  technical: { objective: Point[]; possibleIssues: Point[] };
  creative: Point[];
  suggestions: Point[];
  limitations: string[];
}

interface ApplyCall {
  request: { sessionId?: string; patch?: Record<string, number | null> };
  changes: Array<{ path: string; previous?: number; proposed?: number }>;
  recipe: Recipe;
}

interface Recorder {
  plans: Array<{ recipe: Recipe }>;
  critiques: Critique[];
  applies: ApplyCall[];
  revisions: Array<Record<string, unknown>>;
  saved: Recipe[];
  report: Record<string, unknown> | null;
}

/**
 * The critique is the contract under test, so the assertions read the response
 * bodies the server actually returned instead of only the DOM.
 */
function recordTraffic(page: Page): Recorder {
  const recorder: Recorder = {
    plans: [],
    critiques: [],
    applies: [],
    revisions: [],
    saved: [],
    report: null,
  };
  page.on("response", (response) => {
    const request = response.request();
    const pathname = new URL(response.url()).pathname;
    if (request.method() === "GET" && pathname.startsWith("/api/v1/analysis/")) {
      void response
        .json()
        .catch(() => null)
        .then((body: Record<string, unknown> | null) => {
          if (body === null) {
            return;
          }
          // The report arrives inline on the poll and standalone on /result.
          const report = (body.result ?? body) as Record<string, unknown>;
          if (report && "measurements" in report) {
            recorder.report = report;
          }
        });
      return;
    }
    if (request.method() !== "POST") {
      return;
    }
    if (pathname === PLAN_PATH) {
      void response
        .json()
        .catch(() => ({}))
        .then((body: Record<string, unknown>) => {
          recorder.plans.push({ recipe: (body.recipe ?? {}) as Recipe });
        });
    } else if (pathname === APPLY_PATH) {
      void response
        .json()
        .catch(() => ({}))
        .then((body: Record<string, unknown>) => {
          recorder.applies.push({
            request: JSON.parse(request.postData() ?? "{}") as ApplyCall["request"],
            changes: (body.changes ?? []) as ApplyCall["changes"],
            recipe: (body.recipe ?? {}) as Recipe,
          });
        });
    } else if (pathname === CRITIQUE_PATH) {
      void response
        .json()
        .catch(() => null)
        .then((body: Critique | null) => {
          if (body) {
            recorder.critiques.push(body);
          }
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

/** Parameters that differ from the untouched default of a brand new session. */
function nonzeroAdjustments(recipe: Recipe): Record<string, number> {
  return Object.fromEntries(
    Object.entries(recipe.adjustments ?? {}).filter(
      ([, value]) => typeof value === "number" && value !== 0,
    ),
  ) as Record<string, number>;
}

/** Everything a critique patch must never touch, compared section by section. */
function expectSectionsUntouched(base: Recipe, next: Recipe): void {
  for (const section of [
    "curve",
    "hsl",
    "colorGrading",
    "masks",
    "localAdjustments",
    "output",
  ] as const) {
    expect(JSON.stringify(next[section]), `${section} moved`).toBe(
      JSON.stringify(base[section]),
    );
  }
}

const CITABLE_SECTIONS = [
  "measurements",
  "color",
  "lighting",
  "composition",
  "scene",
  "technicalQuality",
];

/**
 * Mirrors the server validator: an evidence ref must be an identifier the report
 * actually contains, or a real leaf path inside it. `measurement.*` maps onto the
 * plural `measurements` field.
 */
function refResolves(report: Record<string, unknown>, ref: string): boolean {
  const issues = (report.issues ?? []) as Array<{
    id: string;
    regionIds?: string[];
  }>;
  const regions = (report.regions ?? []) as Array<{ id: string }>;
  const subjects = (report.subjects ?? []) as Array<{
    id: string;
    regionId?: string | null;
  }>;
  const identifiers = new Set<string>([
    ...issues.map((issue) => issue.id),
    ...issues.flatMap((issue) => issue.regionIds ?? []),
    ...regions.map((region) => region.id),
    ...subjects.map((subject) => subject.id),
    ...subjects.map((subject) => subject.regionId ?? "").filter(Boolean),
  ]);
  if (identifiers.has(ref) || ref === "instruction" || ref.startsWith("rule.")) {
    return true;
  }

  const [head, ...rest] = ref.split(".");
  const field = head === "measurement" ? "measurements" : head;
  if (!CITABLE_SECTIONS.includes(field ?? "")) {
    return false;
  }
  let node: unknown = (report as Record<string, unknown>)[field ?? ""];
  for (const key of rest) {
    if (node === null || typeof node !== "object" || Array.isArray(node)) {
      return false;
    }
    if (!(key in (node as Record<string, unknown>))) {
      return false;
    }
    node = (node as Record<string, unknown>)[key];
  }
  return node === null || typeof node !== "object";
}

function everyPoint(critique: Critique): Point[] {
  return [
    ...critique.strengths,
    ...critique.technical.objective,
    ...critique.technical.possibleIssues,
    ...critique.creative,
    ...critique.suggestions,
  ];
}

function shot(name: string): string {
  return path.join(ARTIFACTS, `photographer-critique-${name}.png`);
}

function upload(page: Page): Promise<void> {
  return uploadFixture(page, {
    fixtureJson: analysisFixtureJson("desktop-1280x800"),
  });
}

async function openPanel(page: Page): Promise<Locator> {
  await page.getByRole("button", { name: /AI 自动优化/ }).click();
  const panel = page.locator("#photographer-panel");
  await expect(
    panel.getByRole("button", { name: "开始自动优化" }),
  ).toBeVisible();
  // Without a report the critique has nothing to cite, so it stays locked.
  const section = panel.getByRole("region", { name: "AI 摄影点评" });
  await expect(
    section.getByRole("button", { name: "生成摄影点评" }),
  ).toBeDisabled();
  await expect(
    section.getByText("需要先完成这张照片的 AI 摄影分析，点评才有依据。"),
  ).toBeVisible();
  return panel;
}

async function generateCritique(page: Page, panel: Locator): Promise<Locator> {
  const section = panel.getByRole("region", { name: "AI 摄影点评" });
  await expect(section.getByText("规则生成")).toBeVisible();
  await expect(
    section.getByRole("button", { name: "生成摄影点评" }),
  ).toBeEnabled({ timeout: 90_000 });
  await section.getByRole("button", { name: "生成摄影点评" }).click();
  await expect(section.getByRole("region", { name: "后期建议" })).toBeVisible({
    timeout: 90_000,
  });
  await page.screenshot({ path: shot("01-critique") });
  return section;
}

test("the deterministic critique is evidence-linked and honest in the browser", async (
  { page },
  testInfo,
) => {
  test.skip(
    testInfo.project.name !== "desktop-1280x800",
    "the critique panel is verified in the desktop layout",
  );
  const recorder = recordTraffic(page);

  await page.goto("/");
  await upload(page);
  const panel = await openPanel(page);
  await panel.getByRole("button", { name: "开始自动优化" }).click();
  await expect.poll(() => recorder.plans.length, { timeout: 90_000 }).toBe(1);

  const section = await generateCritique(page, panel);
  await expect.poll(() => recorder.critiques.length, { timeout: 60_000 }).toBe(1);
  const critique = recorder.critiques[0]!;

  // Generation is rule based and labelled as such; a mock report stays a mock.
  expect(critique.generatedBy).toBe("deterministic-rules");
  expect(critique.isMock).toBe(true);
  expect(everyPoint(critique).length).toBeGreaterThan(0);

  // No conclusion is free text: each one cites at least one ref, and every ref
  // resolves inside the report the browser is looking at.
  expect(recorder.report).not.toBeNull();
  for (const point of everyPoint(critique)) {
    expect(point.evidenceRefs.length, point.text).toBeGreaterThan(0);
    for (const ref of point.evidenceRefs) {
      expect(refResolves(recorder.report!, ref), `${ref} in ${point.text}`).toBe(
        true,
      );
    }
  }

  // Creative readings never masquerade as measurements.
  expect(critique.creative.length).toBeGreaterThan(0);
  expect(critique.creative.every((point) => point.subjective === true)).toBe(
    true,
  );
  expect(
    critique.technical.objective.every((point) => !point.subjective),
  ).toBe(true);

  for (const title of ["优点", "技术观测", "可能的问题", "创作解读", "后期建议"]) {
    await expect(
      section.getByRole("region", { name: title }),
    ).toBeVisible();
  }
  await expect(
    section.getByText("本次点评基于模拟分析结果（未调用真实视觉模型）"),
  ).toBeVisible();
  await expect(section.getByText("主观", { exact: true })).toHaveCount(
    critique.creative.length,
  );

  // Evidence is collapsed by default and opens on demand.
  const firstDisclosure = section.locator("details").first();
  await expect(firstDisclosure.locator("summary")).toBeVisible();
  await expect(firstDisclosure.locator("li").first()).toBeHidden();
  await firstDisclosure.locator("summary").click();
  await expect(firstDisclosure.locator("li").first()).toBeVisible();
  await page.screenshot({ path: shot("02-evidence-open") });

  // A suggestion with no adjustable parameter stays advice.
  const passive = critique.suggestions.filter(
    (item) =>
      item.recipePatch === null ||
      Object.values(item.recipePatch).every((value) => value === null),
  );
  await expect(
    section.getByText("这条建议不涉及可调参数，需要通过裁切或拍摄时机实现。"),
  ).toHaveCount(passive.length);

  // Same report, same words: regenerating is deterministic.
  await section.getByRole("button", { name: "重新生成点评" }).click();
  await expect.poll(() => recorder.critiques.length, { timeout: 90_000 }).toBe(2);
  expect(JSON.stringify(recorder.critiques[1])).toBe(
    JSON.stringify(recorder.critiques[0]),
  );

  await section.getByRole("button", { name: "收起点评" }).click();
  await expect(
    section.getByRole("button", { name: "生成摄影点评" }),
  ).toBeVisible();
  expect(recorder.revisions).toHaveLength(0);
});

test("applying a critique suggestion previews and accepts through the editor flow", async (
  { page },
  testInfo,
) => {
  test.skip(
    testInfo.project.name !== "desktop-1280x800",
    "the apply entry is verified in the desktop layout",
  );
  const recorder = recordTraffic(page);

  await page.goto("/");
  await upload(page);
  const panel = await openPanel(page);
  await panel.getByRole("button", { name: "开始自动优化" }).click();
  await expect.poll(() => recorder.plans.length, { timeout: 90_000 }).toBe(1);
  const planRecipe = recorder.plans[0]!.recipe;

  const section = await generateCritique(page, panel);
  await expect.poll(() => recorder.critiques.length, { timeout: 60_000 }).toBe(1);
  const suggestion = recorder.critiques[0]!.suggestions.find(
    (item) =>
      item.recipePatch !== null &&
      Object.values(item.recipePatch).some((value) => value !== null),
  )!;
  expect(suggestion).toBeDefined();
  const patchFields = Object.entries(suggestion.recipePatch!)
    .filter(([, value]) => value !== null)
    .map(([key]) => key);
  expect(patchFields.length).toBeGreaterThan(0);

  await section
    .getByRole("listitem")
    .filter({ hasText: suggestion.text })
    .getByRole("button", { name: "应用到编辑" })
    .click();
  await expect.poll(() => recorder.applies.length, { timeout: 90_000 }).toBe(1);
  const applied = recorder.applies[0]!;

  expect(applied.request.sessionId).toMatch(/^[\w-]+$/);
  // The wire intent lists every parameter; only the non-null ones are a change.
  const requested = applied.request.patch ?? {};
  const requestedFields = Object.entries(requested)
    .filter(([, value]) => value !== null)
    .map(([key]) => key);
  expect(requestedFields.sort()).toEqual([...patchFields].sort());
  // The server only moves the parameters this one suggestion named.
  for (const change of applied.changes) {
    expect(change.path.startsWith("adjustments.")).toBe(true);
    expect(patchFields).toContain(change.path.slice("adjustments.".length));
  }
  expect(nonzeroAdjustments(applied.recipe)).toEqual(
    Object.fromEntries(
      applied.changes.map((change) => [
        change.path.slice("adjustments.".length),
        change.proposed,
      ]),
    ),
  );
  expectSectionsUntouched(planRecipe, applied.recipe);

  await expect(
    panel.getByRole("heading", { name: "点评建议预览" }),
  ).toBeVisible();
  await expect(
    panel.getByRole("region", { name: "参数变化" }).getByRole("listitem"),
  ).toHaveCount(applied.changes.length);
  await page.screenshot({ path: shot("03-apply-preview") });

  // A preview is a preview: nothing is written to history until it is accepted.
  expect(recorder.revisions).toHaveLength(0);

  await panel.getByRole("button", { name: "原图" }).click();
  await expect(panel.getByRole("button", { name: "原图" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await panel.getByRole("button", { name: "AI 方案预览" }).click();

  await panel.getByRole("button", { name: "接受方案" }).click();
  await expect
    .poll(() => recorder.saved.length, { timeout: 60_000 })
    .toBe(1);
  expect(recorder.revisions[0]).toMatchObject({ source: "ai" });
  const saved = recorder.saved[0]!;
  expect(nonzeroAdjustments(saved)).toEqual(nonzeroAdjustments(applied.recipe));
  expectSectionsUntouched(planRecipe, saved);

  await expect(
    panel.getByRole("heading", { name: "点评建议预览" }),
  ).toHaveCount(0);
  await expect(page.getByText("已保存")).toBeVisible();
  await page.screenshot({ path: shot("04-accepted") });
});
