// @vitest-environment node
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  onboardingStatePath,
  readOnboardingCompleted,
  resolveFrameDataDir,
  writeOnboardingCompleted,
} from "../lib/onboarding-state";

describe("onboarding state", () => {
  let directory: string;
  let previousDataDir: string | undefined;

  beforeEach(() => {
    directory = fs.mkdtempSync(path.join(os.tmpdir(), "frame-onboarding-test-"));
    previousDataDir = process.env.FRAME_DATA_DIR;
    process.env.FRAME_DATA_DIR = directory;
  });

  afterEach(() => {
    fs.rmSync(directory, { recursive: true, force: true });
    if (previousDataDir === undefined) {
      delete process.env.FRAME_DATA_DIR;
    } else {
      process.env.FRAME_DATA_DIR = previousDataDir;
    }
  });

  it("treats a missing marker as not completed", () => {
    expect(resolveFrameDataDir()).toBe(directory);
    expect(readOnboardingCompleted()).toBe(false);
  });

  it("persists a completion marker", () => {
    const now = new Date("2026-11-12T08:30:00.000Z");

    writeOnboardingCompleted(now);

    expect(readOnboardingCompleted()).toBe(true);
    const document = JSON.parse(
      fs.readFileSync(onboardingStatePath(), "utf8"),
    ) as Record<string, unknown>;
    expect(document).toMatchObject({
      version: 1,
      completed: true,
      completedAt: now.toISOString(),
    });
  });

  it("treats corrupt JSON as not completed", () => {
    fs.writeFileSync(onboardingStatePath(), "{ not-json", "utf8");

    expect(readOnboardingCompleted()).toBe(false);
  });

  it("treats completed: false as not completed", () => {
    fs.writeFileSync(
      onboardingStatePath(),
      JSON.stringify({ version: 1, completed: false }),
      "utf8",
    );

    expect(readOnboardingCompleted()).toBe(false);
  });

  it("does not leave temporary files behind", () => {
    writeOnboardingCompleted(new Date("2026-11-12T08:30:00.000Z"));

    expect(fs.readdirSync(directory)).toEqual(["onboarding.json"]);
  });

  it("fails open when the marker cannot be read for an unexpected reason", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    fs.mkdirSync(onboardingStatePath());

    expect(readOnboardingCompleted()).toBe(true);
    expect(warn).toHaveBeenCalled();
  });
});
