import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import {
  ALPHA_FIXTURE_JSON,
  ARTIFACTS,
  FIXTURE_JSON,
  SIXTEEN_FIXTURE_JSON,
  analysisFixtureJson,
  requirePython,
} from "./support";

function generate(
  target: string,
  name: string,
  variant: number,
  mode = "opaque",
): void {
  const output = execFileSync(
    requirePython(),
    [path.join(__dirname, "generate_fixture.py"), target, String(variant), mode],
    { encoding: "utf8" },
  );
  const metadata = JSON.parse(output.trim().split("\n").at(-1) ?? "{}");
  fs.writeFileSync(name, JSON.stringify(metadata, null, 2), "utf8");
}

export default function globalSetup(): void {
  fs.mkdirSync(ARTIFACTS, { recursive: true });
  generate(path.join(ARTIFACTS, "fixture.jpg"), FIXTURE_JSON, 0);
  generate(path.join(ARTIFACTS, "alpha-fixture.png"), ALPHA_FIXTURE_JSON, 3, "alpha");
  generate(
    path.join(ARTIFACTS, "sixteen-fixture.png"),
    SIXTEEN_FIXTURE_JSON,
    4,
    "sixteen",
  );
  generate(
    path.join(ARTIFACTS, "analysis-fixture-desktop.jpg"),
    analysisFixtureJson("desktop-1280x800"),
    1,
  );
  generate(
    path.join(ARTIFACTS, "analysis-fixture-mobile.jpg"),
    analysisFixtureJson("mobile-390x844"),
    2,
  );
}