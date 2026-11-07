import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useSessionActions } from "@/features/editor/hooks/use-session";
import type { RevisionOutcome } from "@/features/editor/hooks/use-session";
import {
  EditorProvider,
  useEditorStore,
} from "@/features/editor/state/editor-context";
import {
  editorReducer,
  type EditorAction,
  type EditorState,
} from "@/features/editor/state/editor-reducer";
import {
  NEXT_REVISION_ID,
  REVISION_ID,
  SESSION_ID,
  readyEditorState,
  sessionState,
} from "./session-fixtures";
import { photographerPlan } from "./photographer-fixtures";

function wrapperFor(initialState: EditorState) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <EditorProvider initialState={initialState}>{children}</EditorProvider>;
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function errorResponse(code: string, status: number): Response {
  return jsonResponse({ error: { code, message: code, details: {} } }, status);
}

function withProposal(): EditorState {
  return editorReducer(readyEditorState(), {
    type: "proposal-ready",
    plan: photographerPlan(),
  });
}

function dispatch(
  store: ReturnType<typeof useEditorStore>,
  action: EditorAction,
): void {
  act(() => {
    store.dispatch(action);
  });
}

function hookFor(initialState: EditorState) {
  return renderHook(
    () => ({ actions: useSessionActions(), store: useEditorStore() }),
    { wrapper: wrapperFor(initialState) },
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("acceptProposal", () => {
  it("posts the plan recipe as an ai revision and clears the proposal", async () => {
    const posted: Array<{ body: Record<string, unknown>; url: string }> = [];
    const urls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        urls.push(url);
        if (
          url.endsWith(`/api/v1/sessions/${SESSION_ID}/revisions`) &&
          init?.method === "POST"
        ) {
          posted.push({
            url,
            body: JSON.parse(String(init.body)) as Record<string, unknown>,
          });
          return jsonResponse(
            sessionState({
              recipe: photographerPlan().recipe,
              revisionId: NEXT_REVISION_ID,
              revisionNo: 2,
              source: "ai",
              canUndo: true,
            }),
            201,
          );
        }
        if (url.includes("/revisions?limit=50")) {
          return jsonResponse({ items: [], nextCursor: null });
        }
        return errorResponse("not_found", 404);
      }),
    );

    const { result } = hookFor(withProposal());
    const recipe = photographerPlan().recipe;

    let outcome: RevisionOutcome = { ok: false, revisionId: null };
    await act(async () => {
      outcome = await result.current.actions.acceptProposal(recipe);
    });

    expect(outcome).toEqual({ ok: true, revisionId: NEXT_REVISION_ID });
    expect(posted).toHaveLength(1);
    expect(posted[0]?.body.source).toBe("ai");
    expect(posted[0]?.body.parentRevisionId).toBe(REVISION_ID);
    expect(
      (posted[0]?.body.recipe as { adjustments: { contrast: number } }).adjustments
        .contrast,
    ).toBe(12);
    expect(urls.some((url) => url.endsWith("/render"))).toBe(false);
    expect(result.current.store.state.activeRevisionId).toBe(NEXT_REVISION_ID);
    expect(result.current.store.state.committed.adjustments.contrast).toBe(12);
    expect(result.current.store.state.proposal.status).toBe("idle");
  });

  it("refuses to accept while the draft has unsaved changes", async () => {
    const fetchMock = vi.fn(async () => errorResponse("not_found", 404));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = hookFor(withProposal());
    dispatch(result.current.store, {
      type: "draft-adjustment",
      key: "contrast",
      value: 30,
    });

    let outcome: RevisionOutcome = { ok: true, revisionId: REVISION_ID };
    await act(async () => {
      outcome = await result.current.actions.acceptProposal(
        photographerPlan().recipe,
      );
    });

    expect(outcome).toEqual({ ok: false, revisionId: null });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.store.state.activeRevisionId).toBe(REVISION_ID);
    expect(result.current.store.state.proposal.status).toBe("ready");
  });

  it("refreshes and drops a proposal based on a stale revision", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (
          url.endsWith(`/api/v1/sessions/${SESSION_ID}/revisions`) &&
          init?.method === "POST"
        ) {
          return errorResponse("revision_conflict", 409);
        }
        if (url.endsWith(`/api/v1/sessions/${SESSION_ID}`)) {
          return jsonResponse(
            sessionState({
              revisionId: NEXT_REVISION_ID,
              revisionNo: 2,
              canUndo: true,
            }),
          );
        }
        if (url.includes("/revisions?limit=50")) {
          return jsonResponse({ items: [], nextCursor: null });
        }
        return errorResponse("not_found", 404);
      }),
    );

    const { result } = hookFor(withProposal());

    let outcome: RevisionOutcome = { ok: true, revisionId: REVISION_ID };
    await act(async () => {
      outcome = await result.current.actions.acceptProposal(
        photographerPlan().recipe,
      );
    });

    expect(outcome).toEqual({ ok: false, revisionId: null });
    expect(result.current.store.state.activeRevisionId).toBe(NEXT_REVISION_ID);
    expect(result.current.store.state.proposal.status).toBe("idle");
    expect(result.current.store.state.notice).toBe("版本已变化，已为你刷新。");
  });
});
