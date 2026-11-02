import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import { ARTIFACTS, FIXTURE_JSON, requirePython } from "./support";

export default function globalSetup(): void {
  fs.mkdirSync(ARTIFACTS, { recursive: true });
  const fixturePath = path.join(ARTIFACTS, "fixture.jpg");
  const output = execFileSync(
    requirePython(),
    [path.join(__dirname, "generate_fixture.py"), fixturePath],
    { encoding: "utf8" },
  );
  const metadata = JSON.parse(output.trim().split("\n").at(-1) ?? "{}");
  fs.writeFileSync(FIXTURE_JSON, JSON.stringify(metadata, null, 2), "utf8");
}
