import fs from "node:fs";
import path from "node:path";

const ONBOARDING_FILENAME = "onboarding.json";
const ONBOARDING_VERSION = 1;

/**
 * Resolves the same data directory the API token and provider settings use.
 * `FRAME_DATA_DIR` must be set to a user-writable directory in a packaged app;
 * the repository data directory is only the development fallback.
 */
export function resolveFrameDataDir(): string {
  const configured = process.env.FRAME_DATA_DIR?.trim();
  if (configured) {
    return configured;
  }
  return path.resolve(process.cwd(), "..", "..", "data");
}

export function onboardingStatePath(dataDir = resolveFrameDataDir()): string {
  return path.join(dataDir, ONBOARDING_FILENAME);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isMissingFile(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    (error as NodeJS.ErrnoException).code === "ENOENT"
  );
}

/**
 * Reads the persisted onboarding marker.
 *
 * A missing or corrupt marker means "not completed" so the user can see the
 * onboarding again. Unexpected I/O or permission failures fail open: locking
 * the user out of the workbench because a small state file cannot be read is
 * worse than showing the app without onboarding.
 */
export function readOnboardingCompleted(): boolean {
  const file = onboardingStatePath();
  let raw: string;
  try {
    raw = fs.readFileSync(file, "utf8");
  } catch (error) {
    if (isMissingFile(error)) {
      return false;
    }
    console.warn("Unable to read onboarding state; assuming completed.", error);
    return true;
  }

  try {
    const parsed: unknown = JSON.parse(raw);
    return isRecord(parsed) && parsed.completed === true;
  } catch {
    return false;
  }
}

/**
 * Writes the completion marker atomically so a crash cannot leave a half-written
 * JSON document that would incorrectly be treated as completed.
 */
export function writeOnboardingCompleted(now = new Date()): void {
  const dataDir = resolveFrameDataDir();
  fs.mkdirSync(dataDir, { recursive: true });

  const target = onboardingStatePath(dataDir);
  const temp = `${target}.${process.pid}.${now.getTime()}.tmp`;
  const payload = `${JSON.stringify(
    {
      version: ONBOARDING_VERSION,
      completed: true,
      completedAt: now.toISOString(),
    },
    null,
    2,
  )}\n`;

  try {
    fs.writeFileSync(temp, payload, { encoding: "utf8", mode: 0o600 });
    fs.renameSync(temp, target);
  } catch (error) {
    try {
      fs.rmSync(temp, { force: true });
    } catch {
      // Best effort cleanup; the original error is the useful one.
    }
    throw error;
  }
}
