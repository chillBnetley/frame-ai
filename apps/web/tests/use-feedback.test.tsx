import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  useFeedback,
  type FeedbackDecision,
} from "@/features/photographer/hooks/use-feedback";
import { FEEDBACK_ID, feedbackRecord, feedbackSummary } from "./feedback-fixtures";
import { PLAN_ID } from "./photographer-fixtures";
import { REVISION_ID, SESSION_ID } from "./session-fixtures";

const POST_URL = "/api/v1/ai/photographer/feedback";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function errorResponse(code: string, status: number): Response {
  return jsonResponse({ error: { code, message: code, details: {} } }, status);
}

function accepted(overrides: Partial<FeedbackDecision> = {}): FeedbackDecision {
  return {
    action: "accepted",
    source: "plan",
    planId: PLAN_ID,
    revisionId: REVISION_ID,
    ...overrides,
  };
}

interface FeedbackServer {
  posts: Record<string, unknown>[];
  deletes: string[];
  stopFailingPosts(): void;
  failDeletes(): void;
}

/**
 * A stand-in for the feedback endpoint: POST stores, GET lists what was
 * stored, DELETE removes it. Failures can be switched on and off per call.
 */
function stubFeedbackEndpoint(
  options: { failPost?: boolean; list?: () => unknown } = {},
): FeedbackServer {
  const posts: Record<string, unknown>[] = [];
  const deletes: string[] = [];
  let postFails = options.failPost ?? false;
  let deleteFails = false;

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      if (url.pathname === POST_URL && init?.method === "POST") {
        if (postFails) {
          return errorResponse("storage_error", 500);
        }
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        posts.push(body);
        return jsonResponse(feedbackRecord({ id: String(posts.length) }), 201);
      }
      if (url.pathname.startsWith(`${POST_URL}/`)) {
        if (deleteFails) {
          return errorResponse("storage_error", 500);
        }
        deletes.push(url.pathname.slice(POST_URL.length + 1));
        return new Response(null, { status: 204 });
      }
      if (options.list !== undefined) {
        return jsonResponse(options.list());
      }
      return jsonResponse({
        items: posts.map((_, index) => feedbackRecord({ id: String(index + 1) })),
        summary: feedbackSummary({ total: posts.length, accepted: posts.length }),
      });
    }),
  );

  return {
    posts,
    deletes,
    stopFailingPosts: () => {
      postFails = false;
    },
    failDeletes: () => {
      deleteFails = true;
    },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useFeedback", () => {
  it("posts the decision and reloads the history", async () => {
    const server = stubFeedbackEndpoint();
    const { result } = renderHook(() => useFeedback(SESSION_ID));

    let stored = false;
    await act(async () => {
      stored = await result.current.record(accepted());
    });

    expect(stored).toBe(true);
    expect(server.posts).toEqual([
      {
        sessionId: SESSION_ID,
        action: "accepted",
        source: "plan",
        planId: PLAN_ID,
        revisionId: REVISION_ID,
      },
    ]);
    await waitFor(() => {
      expect(result.current.items).toHaveLength(1);
      expect(result.current.summary?.total).toBe(1);
    });
  });

  it("sends only the fields the contract allows", async () => {
    const server = stubFeedbackEndpoint();
    const { result } = renderHook(() => useFeedback(SESSION_ID));

    await act(async () => {
      await result.current.record({
        ...accepted(),
        ...( { notes: "把天空调亮一点", instruction: "更暖一些" } as Record<
          string,
          unknown
        >),
      });
    });

    expect(Object.keys(server.posts[0] ?? {}).sort()).toEqual([
      "action",
      "planId",
      "revisionId",
      "sessionId",
      "source",
    ]);
  });

  it("keeps a failed decision queued, reports it, and retries on demand", async () => {
    const server = stubFeedbackEndpoint({ failPost: true });
    const { result } = renderHook(() => useFeedback(SESSION_ID));

    let stored = true;
    await act(async () => {
      stored = await result.current.record(accepted());
    });

    expect(stored).toBe(false);
    expect(result.current.unsent).toBe(1);
    expect(result.current.sendError?.code).toBe("storage_error");
    expect(result.current.items).toEqual([]);

    server.stopFailingPosts();
    let retried = false;
    await act(async () => {
      retried = await result.current.retryUnsent();
    });

    expect(retried).toBe(true);
    expect(result.current.unsent).toBe(0);
    expect(result.current.sendError).toBeNull();
    expect(server.posts).toHaveLength(1);
  });

  it("replaces a queued decision with the newest one for the same anchor", async () => {
    const server = stubFeedbackEndpoint({ failPost: true });
    const { result } = renderHook(() => useFeedback(SESSION_ID));

    await act(async () => {
      await result.current.record(accepted());
    });
    await act(async () => {
      await result.current.record(accepted({ rubric: { exposure: 4 } }));
    });
    expect(result.current.unsent).toBe(1);

    server.stopFailingPosts();
    await act(async () => {
      expect(await result.current.retryUnsent()).toBe(true);
    });

    expect(server.posts).toEqual([
      {
        sessionId: SESSION_ID,
        action: "accepted",
        source: "plan",
        planId: PLAN_ID,
        revisionId: REVISION_ID,
        rubric: { exposure: 4 },
      },
    ]);
  });

  it("opens the rating dialog only after the decision is stored", async () => {
    stubFeedbackEndpoint();
    const stored = renderHook(() => useFeedback(SESSION_ID));
    await act(async () => {
      expect(await stored.result.current.recordAndAskForRating(accepted())).toBe(
        true,
      );
    });
    expect(stored.result.current.rating).toEqual(accepted());

    stubFeedbackEndpoint({ failPost: true });
    const failing = renderHook(() => useFeedback(SESSION_ID));
    await act(async () => {
      expect(
        await failing.result.current.recordAndAskForRating(accepted()),
      ).toBe(false);
    });
    expect(failing.result.current.rating).toBeNull();
  });

  it("re-records the same decision with the rubric when the rating is submitted", async () => {
    const server = stubFeedbackEndpoint();
    const { result } = renderHook(() => useFeedback(SESSION_ID));

    await act(async () => {
      await result.current.recordAndAskForRating(accepted());
    });
    await act(async () => {
      expect(await result.current.submitRating({ exposure: 4, skinTone: 2 })).toBe(
        true,
      );
    });

    expect(result.current.rating).toBeNull();
    expect(server.posts[1]).toEqual({
      sessionId: SESSION_ID,
      action: "accepted",
      source: "plan",
      planId: PLAN_ID,
      revisionId: REVISION_ID,
      rubric: { exposure: 4, skinTone: 2 },
    });
  });

  it("sends nothing more when the rating is skipped", async () => {
    const server = stubFeedbackEndpoint();
    const { result } = renderHook(() => useFeedback(SESSION_ID));

    await act(async () => {
      await result.current.recordAndAskForRating(accepted());
    });
    act(() => {
      result.current.dismissRating();
    });

    expect(result.current.rating).toBeNull();
    expect(server.posts).toHaveLength(1);
    await act(async () => {
      expect(await result.current.submitRating({ exposure: 5 })).toBe(false);
    });
    expect(server.posts).toHaveLength(1);
  });

  it("sends a rejection without a revision anchor", async () => {
    const server = stubFeedbackEndpoint();
    const { result } = renderHook(() => useFeedback(SESSION_ID));

    await act(async () => {
      await result.current.record({
        action: "rejected",
        source: "chat",
        planId: PLAN_ID,
        revisionId: null,
      });
    });

    expect(server.posts[0]).toEqual({
      sessionId: SESSION_ID,
      action: "rejected",
      source: "chat",
      planId: PLAN_ID,
    });
  });

  it("restores the list when a delete fails", async () => {
    const server = stubFeedbackEndpoint();
    const { result } = renderHook(() => useFeedback(SESSION_ID));

    await act(async () => {
      await result.current.record(accepted());
    });
    expect(result.current.items).toHaveLength(1);

    server.failDeletes();
    await act(async () => {
      await result.current.remove(FEEDBACK_ID);
    });

    expect(result.current.items).toHaveLength(1);
    expect(result.current.historyError?.code).toBe("storage_error");
  });

  it("starts clean for a new session and sends nothing without one", async () => {
    const server = stubFeedbackEndpoint();
    const { result, rerender } = renderHook(
      ({ sessionId }: { sessionId: string | null }) => useFeedback(sessionId),
      { initialProps: { sessionId: SESSION_ID as string | null } },
    );

    await act(async () => {
      await result.current.record(accepted());
    });
    expect(result.current.items).toHaveLength(1);

    rerender({ sessionId: null });
    await act(async () => {
      expect(await result.current.record(accepted())).toBe(false);
    });

    expect(server.posts).toHaveLength(1);
    expect(result.current.items).toEqual([]);
    expect(result.current.summary).toBeNull();
    expect(result.current.unsent).toBe(0);
  });
});
