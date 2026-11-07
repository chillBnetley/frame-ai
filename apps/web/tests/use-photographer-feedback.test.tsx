import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { UseAnalysisResult } from "@/features/analysis/hooks/use-analysis";
import { EditorProvider } from "@/features/editor/state/editor-context";
import {
  editorReducer,
  type EditorState,
} from "@/features/editor/state/editor-reducer";
import { usePhotographer } from "@/features/photographer/hooks/use-photographer";
import type { PhotographerPlanResponse } from "@/types/photographer";
import { analysisReport } from "./analysis-fixtures";
import {
  PLAN_ID,
  PATCH_ID,
  critiqueApply,
  photographerPatch,
  photographerPlan,
} from "./photographer-fixtures";
import {
  NEXT_REVISION_ID,
  SESSION_ID,
  readyEditorState,
  sessionState,
} from "./session-fixtures";

const FEEDBACK_URL = "/api/v1/ai/photographer/feedback";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function analysisState(): UseAnalysisResult {
  return {
    analysisId: null,
    status: "completed",
    stage: null,
    isMock: true,
    report: analysisReport(),
    error: null,
    requestPending: false,
    running: false,
    start: vi.fn(),
    retry: vi.fn(),
    rerun: vi.fn(),
  };
}

interface FeedbackServer {
  posts: Record<string, unknown>[];
}

/** Accept the revision POST and record every feedback POST made afterwards. */
function stubFlows(options: { failFeedback?: boolean } = {}): FeedbackServer {
  const posts: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const method = init?.method;
      if (url.pathname.endsWith("/revisions") && method === "POST") {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        return jsonResponse(
          sessionState({
            recipe: body.recipe as PhotographerPlanResponse["recipe"],
            revisionId: NEXT_REVISION_ID,
            revisionNo: 2,
            source: "ai",
            canUndo: true,
          }),
          201,
        );
      }
      if (url.pathname.includes("/revisions")) {
        return jsonResponse({ items: [], nextCursor: null });
      }
      if (url.pathname === FEEDBACK_URL && method === "POST") {
        if (options.failFeedback) {
          return jsonResponse(
            { error: { code: "storage_error", message: "x", details: {} } },
            500,
          );
        }
        posts.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
        return jsonResponse({ ok: true }, 201);
      }
      if (url.pathname === FEEDBACK_URL) {
        return jsonResponse({ items: [], summary: null });
      }
      return jsonResponse({}, 404);
    }),
  );
  return { posts };
}

function withProposal(state: EditorState): EditorState {
  return editorReducer(state, { type: "proposal-ready", plan: photographerPlan() });
}

function withChatPatch(state: EditorState): EditorState {
  return editorReducer(state, { type: "patch-ready", patch: photographerPatch() });
}

function withCritiquePatch(state: EditorState): EditorState {
  return editorReducer(state, {
    type: "critique-ready",
    patch: critiqueApply(),
  });
}

function renderPhotographer(build: (base: EditorState) => EditorState) {
  const initial = build(readyEditorState());
  function Wrapper({ children }: { children: ReactNode }) {
    return <EditorProvider initialState={initial}>{children}</EditorProvider>;
  }
  return renderHook(() => usePhotographer(analysisState()), { wrapper: Wrapper });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("usePhotographer feedback", () => {
  it("records an accepted plan with its plan and revision anchors", async () => {
    const server = stubFlows();
    const { result } = renderPhotographer(withProposal);

    await act(async () => {
      expect(await result.current.accept()).toBe(true);
    });

    expect(server.posts).toEqual([
      {
        sessionId: SESSION_ID,
        action: "accepted",
        source: "plan",
        planId: PLAN_ID,
        revisionId: NEXT_REVISION_ID,
      },
    ]);
    expect(result.current.feedback.rating).toEqual({
      action: "accepted",
      source: "plan",
      planId: PLAN_ID,
      revisionId: NEXT_REVISION_ID,
    });
  });

  it("records a chat patch against the patch row, not the plan", async () => {
    const server = stubFlows();
    const { result } = renderPhotographer(withChatPatch);

    await act(async () => {
      expect(await result.current.accept()).toBe(true);
    });

    expect(server.posts[0]).toMatchObject({
      action: "accepted",
      source: "chat",
      planId: PATCH_ID,
    });
  });

  it("records a critique without a plan reference", async () => {
    const server = stubFlows();
    const { result } = renderPhotographer(withCritiquePatch);

    await act(async () => {
      expect(await result.current.accept()).toBe(true);
    });

    expect(server.posts[0]).toEqual({
      sessionId: SESSION_ID,
      action: "accepted",
      source: "critique",
      revisionId: NEXT_REVISION_ID,
    });
  });

  it("records abandoning as a rejection with no revision anchor", async () => {
    const server = stubFlows();
    const { result } = renderPhotographer(withProposal);

    await act(async () => {
      await result.current.abandon();
    });

    expect(server.posts).toEqual([
      {
        sessionId: SESSION_ID,
        action: "rejected",
        source: "plan",
        planId: PLAN_ID,
      },
    ]);
    expect(result.current.proposal.status).toBe("idle");
  });

  it("records nothing when there was no proposal to reject", async () => {
    const server = stubFlows();
    const { result } = renderPhotographer((state) => state);

    await act(async () => {
      await result.current.abandon();
    });

    expect(server.posts).toEqual([]);
  });

  it("keeps the accepted revision and queues the decision when feedback fails", async () => {
    const server = stubFlows({ failFeedback: true });
    const { result } = renderPhotographer(withProposal);

    await act(async () => {
      expect(await result.current.accept()).toBe(true);
    });

    expect(result.current.proposal.status).toBe("idle");
    expect(result.current.feedback.unsent).toBe(1);
    expect(result.current.feedback.rating).toBeNull();
    expect(server.posts).toEqual([]);
  });
});
