import {
  expect,
  type Page,
  type Request,
  type Response,
} from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

export const ROOT = path.resolve(__dirname, "../..");
export const ARTIFACTS = path.join(ROOT, "tests", "e2e", ".artifacts");
export const FIXTURE_JSON = path.join(ARTIFACTS, "fixture.json");

export function analysisFixtureJson(projectName: string): string {
  const variant = projectName.includes("mobile") ? "mobile" : "desktop";
  return path.join(ARTIFACTS, `analysis-fixture-${variant}.json`);
}

export const PYTHON =
  process.env.E2E_PYTHON ??
  (process.platform === "win32"
    ? path.join(ROOT, "services", "api", ".venv", "Scripts", "python.exe")
    : path.join(ROOT, "services", "api", ".venv", "bin", "python"));

export function requirePython(): string {
  if (!fs.existsSync(PYTHON)) {
    throw new Error(
      `Python virtualenv not found at ${PYTHON}. Create services/api/.venv or set E2E_PYTHON.`,
    );
  }
  return PYTHON;
}

const UPLOAD_PATH = "/api/v1/images";
const UPLOAD_RESPONSE_TIMEOUT = 90_000;

function fixturePathFromMetadata(fixtureJson: string): string {
  const metadata = JSON.parse(fs.readFileSync(fixtureJson, "utf8")) as {
    path?: string;
  };
  if (typeof metadata.path !== "string" || metadata.path.length === 0) {
    throw new Error(`${fixtureJson} does not contain a fixture image path.`);
  }
  return metadata.path;
}

function isUploadRequest(request: Request): boolean {
  return (
    request.method() === "POST" && new URL(request.url()).pathname === UPLOAD_PATH
  );
}

function isUploadResponse(response: Response): boolean {
  return isUploadRequest(response.request());
}

/**
 * Waits until the workspace has hydrated and its mount effects have settled.
 *
 * The page is server-rendered, so the file input exists before React is ready. A
 * file chosen inside that window can be dropped, and in dev the Strict Mode
 * mount/unmount replay runs the upload effect cleanup, which aborts the request
 * (observed as `net::ERR_ABORTED` and a 120 s `waitForResponse` timeout). The
 * health badge is only painted after a fetch resolves following that commit, so
 * its "API 已连接" label is a reliable readiness barrier.
 */
export async function waitForAppReady(page: Page): Promise<void> {
  const health = page.locator('span[role="status"][title*="FastAPI"]');
  await expect(health).toContainText("API 已连接", { timeout: 30_000 });
}

export async function openApp(page: Page): Promise<void> {
  await page.goto("/");
  await waitForAppReady(page);
}

export interface UploadFixtureOptions {
  /** Fixture metadata JSON written by global-setup; defaults to the standard fixture. */
  fixtureJson?: string;
  /** Direct path to the image file; overrides `fixtureJson`. */
  fixturePath?: string;
  /** Test id of the upload input (defaults to `file-input`). */
  inputTestId?: string;
  /** Accessible label of the upload input, used by the "replace photo" control. */
  inputLabel?: string;
}

/**
 * Uploads a fixture through the browser pipeline and waits for the editor preview.
 *
 * Matches any `POST /api/v1/images` response first so a non-201 status surfaces
 * with the API error body instead of being filtered out by the predicate, and
 * races the response against `requestfailed` so an aborted request fails
 * immediately rather than after the test timeout.
 */
export async function uploadFixture(
  page: Page,
  options: UploadFixtureOptions = {},
): Promise<void> {
  await waitForAppReady(page);
  const fixturePath =
    options.fixturePath ??
    fixturePathFromMetadata(options.fixtureJson ?? FIXTURE_JSON);
  const input = options.inputLabel
    ? page.locator(`input[aria-label="${options.inputLabel}"]`)
    : page.getByTestId(options.inputTestId ?? "file-input");
  await expect(input).toBeAttached();

  const responsePromise = page.waitForResponse(isUploadResponse, {
    timeout: UPLOAD_RESPONSE_TIMEOUT,
  });
  const failurePromise = page
    .waitForEvent("requestfailed", {
      predicate: isUploadRequest,
      timeout: UPLOAD_RESPONSE_TIMEOUT,
    })
    .then((request) => {
      throw new Error(
        `Upload request failed: ${request.failure()?.errorText ?? "unknown error"}`,
      );
    });
  // Both waits outlive the race on the winning path; keep them from becoming
  // unhandled rejections once the other side times out.
  void responsePromise.catch(() => undefined);
  void failurePromise.catch(() => undefined);

  await input.setInputFiles(fixturePath);
  const response = await Promise.race([responsePromise, failurePromise]);
  const detail = await response.text().catch(() => "");
  expect(
    response.status(),
    `Upload failed with HTTP ${response.status()}: ${detail.slice(0, 300)}`,
  ).toBe(201);
  await expect(page.getByRole("heading", { name: "编辑预览" })).toBeVisible();
  await expect(page.getByAltText("编辑后的预览")).toBeVisible({ timeout: 60_000 });
}
