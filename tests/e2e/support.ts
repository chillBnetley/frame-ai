import fs from "node:fs";
import path from "node:path";

export const ROOT = path.resolve(__dirname, "../..");
export const ARTIFACTS = path.join(ROOT, "tests", "e2e", ".artifacts");
export const FIXTURE_JSON = path.join(ARTIFACTS, "fixture.json");

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
