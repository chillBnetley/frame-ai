import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { nextRenderSeq } from "@/lib/render-seq";

describe("nextRenderSeq", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-11-04T00:00:00.000Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("stays strictly increasing while the clock is frozen", () => {
    const issued = Array.from({ length: 50 }, () => nextRenderSeq());

    expect(new Set(issued).size).toBe(issued.length);
    issued.forEach((value, index) => {
      if (index > 0) {
        expect(value).toBeGreaterThan(issued[index - 1]);
      }
    });
  });

  it("re-anchors to the clock once it advances past the counter", () => {
    const before = nextRenderSeq();

    vi.setSystemTime(new Date("2026-11-04T00:00:05.000Z"));
    const after = nextRenderSeq();

    expect(after).toBeGreaterThan(before);
    expect(after).toBe(Date.now());
  });
});
