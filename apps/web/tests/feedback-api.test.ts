import { afterEach, describe, expect, it, vi } from "vitest";

import {
  deleteFeedback,
  fetchFeedback,
  recordFeedback,
} from "@/lib/api/photographer";
import { feedbackRecord, feedbackSummary } from "./feedback-fixtures";
import { PLAN_ID } from "./photographer-fixtures";
import { IMAGE_ID, SESSION_ID } from "./session-fixtures";

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubJson(body: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    ),
  );
}

function recordedCalls(): { url: string; method?: string; body?: string }[] {
  const fetchMock = vi.mocked(fetch);
  return fetchMock.mock.calls.map(([input, init]) => ({
    url: String(input),
    method: init?.method,
    body: typeof init?.body === "string" ? init.body : undefined,
  }));
}

describe("feedback api client", () => {
  it("posts a feedback request as json", async () => {
    stubJson(feedbackRecord());

    await recordFeedback({
      sessionId: SESSION_ID,
      action: "accepted",
      planId: PLAN_ID,
    });

    const [call] = recordedCalls();
    expect(call?.url).toContain("/api/v1/ai/photographer/feedback");
    expect(call?.method).toBe("POST");
    expect(JSON.parse(call?.body ?? "{}")).toEqual({
      sessionId: SESSION_ID,
      action: "accepted",
      planId: PLAN_ID,
    });
  });

  it("builds only the filters that were given", async () => {
    stubJson({ items: [], summary: feedbackSummary() });

    await fetchFeedback({ imageId: IMAGE_ID, limit: 5 });

    const [call] = recordedCalls();
    const url = new URL(call?.url ?? "", "http://localhost");
    expect(url.pathname).toBe("/api/v1/ai/photographer/feedback");
    expect(url.searchParams.toString()).toBe(`imageId=${IMAGE_ID}&limit=5`);
  });

  it("omits the query string entirely when no filter is given", async () => {
    stubJson({ items: [], summary: feedbackSummary() });

    await fetchFeedback();

    expect(recordedCalls()[0]?.url).toBe(
      "/api/v1/ai/photographer/feedback",
    );
  });

  it("accepts the empty 204 body of a delete", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 204 })));

    await expect(deleteFeedback(PLAN_ID)).resolves.toBeUndefined();
    expect(recordedCalls()[0]).toEqual({
      url: `/api/v1/ai/photographer/feedback/${PLAN_ID}`,
      method: "DELETE",
      body: undefined,
    });
  });
});
