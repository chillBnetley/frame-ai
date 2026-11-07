import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  useSessionActions,
  useSessionRestore,
} from "@/features/editor/hooks/use-session";
import {
  EditorProvider,
  useEditorStore,
} from "@/features/editor/state/editor-context";
import {
  createInitialEditorState,
  type EditorAction,
  type EditorState,
} from "@/features/editor/state/editor-reducer";
import { withAdjustment } from "@/lib/recipe";
import type { EditRecipe } from "@/types/session";
import {
  NEXT_REVISION_ID,
  REVISION_ID,
  SESSION_ID,
  readyEditorState,
  sessionState,
} from "./session-fixtures";

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

function errorResponse(code: string, status: number, details: Record<string, unknown> = {}) {
  return jsonResponse({ error: { code, message: code, details } }, status);
}

function actionsHook(initialState: EditorState) {
  return renderHook(
    () => ({ actions: useSessionActions(), store: useEditorStore() }),
    { wrapper: wrapperFor(initialState) },
  );
}

function dispatch(
  store: ReturnType<typeof useEditorStore>,
  action: EditorAction,
): void {
  act(() => {
    store.dispatch(action);
  });
}

function editedState(): EditorState {
  return readyEditorState();
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
});

describe("useSessionRestore", () => {
  it("restores the session referenced by ?session=", async () => {
    window.history.replaceState({}, "", `/?session=${SESSION_ID}`);
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith(`/api/v1/sessions/${SESSION_ID}`)) {
        return jsonResponse(sessionState({ canUndo: true }));
      }
      if (url.includes(`/api/v1/sessions/${SESSION_ID}/revisions`)) {
        return jsonResponse({ items: [], nextCursor: null });
      }
      return errorResponse("not_found", 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(
      () => {
        useSessionRestore();
        return useEditorStore();
      },
      { wrapper: wrapperFor(createInitialEditorState()) },
    );

    await waitFor(() => expect(result.current.state.phase).toBe("ready"));
    expect(result.current.state.sessionId).toBe(SESSION_ID);
    expect(result.current.state.canUndo).toBe(true);
    expect(window.location.search).toBe(`?session=${SESSION_ID}`);
  });

  it("clears the URL and reports a missing session", async () => {
    window.history.replaceState({}, "", `/?session=${SESSION_ID}`);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => errorResponse("session_not_found", 404)),
    );

    const { result } = renderHook(
      () => {
        useSessionRestore();
        return useEditorStore();
      },
      { wrapper: wrapperFor(createInitialEditorState()) },
    );

    await waitFor(() => expect(result.current.state.error?.code).toBe("session_not_found"));
    expect(result.current.state.phase).toBe("empty");
    expect(window.location.search).toBe("");
  });
});

describe("useSessionActions.commit", () => {
  it("posts a revision with an idempotency key and adopts the server state", async () => {
    const posted: Array<{ body: Record<string, unknown>; headers: Headers }> = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith(`/api/v1/sessions/${SESSION_ID}/revisions`) && init?.method === "POST") {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        posted.push({ body, headers: new Headers(init.headers) });
        return jsonResponse(
          sessionState({
            recipe: body.recipe as EditRecipe,
            revisionId: NEXT_REVISION_ID,
            revisionNo: 2,
            canUndo: true,
          }),
          201,
        );
      }
      if (url.includes("/revisions?limit=50")) {
        return jsonResponse({ items: [], nextCursor: null });
      }
      return errorResponse("not_found", 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = actionsHook(editedState());
    dispatch(result.current.store, { type: "draft-adjustment", key: "contrast", value: 20 });

    let saved = false;
    await act(async () => {
      saved = await result.current.actions.commit();
    });

    expect(saved).toBe(true);
    expect(posted).toHaveLength(1);
    expect(posted[0]?.body.parentRevisionId).toBe(REVISION_ID);
    expect(posted[0]?.body.source).toBe("user");
    expect(posted[0]?.headers.get("Idempotency-Key")).toMatch(/[0-9a-f-]{16,}/);
    expect(result.current.store.state.activeRevisionId).toBe(NEXT_REVISION_ID);
    expect(result.current.store.state.committed.adjustments.contrast).toBe(20);
    expect(result.current.store.state.save.status).toBe("saved");
  });

  it("retains the draft and reuses the key when retrying a failed save", async () => {
    const keys: Array<string | null> = [];
    let attempts = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith(`/api/v1/sessions/${SESSION_ID}/revisions`) && init?.method === "POST") {
          attempts += 1;
          keys.push(new Headers(init.headers).get("Idempotency-Key"));
          if (attempts === 1) {
            return errorResponse("storage_error", 500);
          }
          const body = JSON.parse(String(init.body)) as Record<string, unknown>;
          return jsonResponse(
            sessionState({
              recipe: body.recipe as EditRecipe,
              revisionId: NEXT_REVISION_ID,
              revisionNo: 2,
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

    const { result } = actionsHook(editedState());
    dispatch(result.current.store, { type: "draft-adjustment", key: "contrast", value: 20 });

    await act(async () => {
      expect(await result.current.actions.commit()).toBe(false);
    });
    expect(result.current.store.state.draft.adjustments.contrast).toBe(20);
    expect(result.current.store.state.save.status).toBe("error");
    expect(result.current.store.state.save.idempotencyKey).not.toBeNull();

    await act(async () => {
      expect(await result.current.actions.commit()).toBe(true);
    });
    expect(attempts).toBe(2);
    expect(keys[0]).not.toBeNull();
    expect(keys[1]).toBe(keys[0]);
    expect(result.current.store.state.save.status).toBe("saved");
  });

  it("refreshes the session on conflict without overwriting the draft", async () => {
    const freshRecipe = withAdjustment(readyEditorState().draft, "contrast", 55);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith(`/api/v1/sessions/${SESSION_ID}/revisions`) && init?.method === "POST") {
          return errorResponse("revision_conflict", 409, {
            activeRevisionId: NEXT_REVISION_ID,
          });
        }
        if (url.endsWith(`/api/v1/sessions/${SESSION_ID}`)) {
          return jsonResponse(
            sessionState({
              recipe: freshRecipe,
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

    const { result } = actionsHook(editedState());
    dispatch(result.current.store, { type: "draft-adjustment", key: "contrast", value: 30 });

    await act(async () => {
      expect(await result.current.actions.commit()).toBe(false);
    });

    expect(result.current.store.state.draft.adjustments.contrast).toBe(30);
    expect(result.current.store.state.committed.adjustments.contrast).toBe(55);
    expect(result.current.store.state.activeRevisionId).toBe(NEXT_REVISION_ID);
    expect(result.current.store.state.notice).toBe("版本已变化，已为你刷新。");
    expect(result.current.store.state.save.idempotencyKey).toBeNull();
  });
});

describe("useSessionActions history", () => {
  it("sends the expected revision on undo and replaces local state", async () => {
    const posted: Array<Record<string, unknown>> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith(`/api/v1/sessions/${SESSION_ID}/undo`) && init?.method === "POST") {
          posted.push(JSON.parse(String(init.body)) as Record<string, unknown>);
          return jsonResponse(sessionState({ canRedo: true }));
        }
        if (url.includes("/revisions?limit=50")) {
          return jsonResponse({ items: [], nextCursor: null });
        }
        return errorResponse("not_found", 404);
      }),
    );

    const ready = readyEditorState(
      withAdjustment(readyEditorState().draft, "contrast", 18),
      { revisionId: NEXT_REVISION_ID, revisionNo: 2, canUndo: true },
    );
    const { result } = actionsHook(ready);

    await act(async () => {
      expect(await result.current.actions.undo()).toEqual({
        ok: true,
        revisionId: REVISION_ID,
      });
    });

    expect(posted).toEqual([{ revisionId: NEXT_REVISION_ID }]);
    expect(result.current.store.state.committed.adjustments.contrast).toBe(0);
    expect(result.current.store.state.draft.adjustments.contrast).toBe(0);
    expect(result.current.store.state.canRedo).toBe(true);
  });

  it("saves a dirty draft before undo and targets the saved revision", async () => {
    const calls: Array<{ path: string; body: Record<string, unknown> }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith(`/api/v1/sessions/${SESSION_ID}/revisions`) && init?.method === "POST") {
          const body = JSON.parse(String(init.body)) as Record<string, unknown>;
          calls.push({ path: "revision", body });
          return jsonResponse(
            sessionState({
              recipe: body.recipe as EditRecipe,
              revisionId: NEXT_REVISION_ID,
              revisionNo: 2,
              canUndo: true,
            }),
            201,
          );
        }
        if (url.endsWith(`/api/v1/sessions/${SESSION_ID}/undo`) && init?.method === "POST") {
          calls.push({
            path: "undo",
            body: JSON.parse(String(init.body)) as Record<string, unknown>,
          });
          return jsonResponse(sessionState({ canRedo: true }));
        }
        if (url.includes("/revisions?limit=50")) {
          return jsonResponse({ items: [], nextCursor: null });
        }
        return errorResponse("not_found", 404);
      }),
    );

    const { result } = actionsHook(readyEditorState(undefined, { canUndo: true }));
    dispatch(result.current.store, { type: "draft-adjustment", key: "contrast", value: 20 });

    await act(async () => {
      expect(await result.current.actions.undo()).toEqual({
        ok: true,
        revisionId: REVISION_ID,
      });
    });

    expect(calls.map((call) => call.path)).toEqual(["revision", "undo"]);
    expect(calls[1]?.body).toEqual({ revisionId: NEXT_REVISION_ID });
    expect(result.current.store.state.draft.adjustments.contrast).toBe(0);
    expect(result.current.store.state.save.status).toBe("saved");
  });

  it("keeps the dirty draft and skips undo when the pre-history save fails", async () => {
    const urls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        urls.push(url);
        if (url.endsWith(`/api/v1/sessions/${SESSION_ID}/revisions`) && init?.method === "POST") {
          return errorResponse("storage_error", 500);
        }
        if (url.endsWith(`/api/v1/sessions/${SESSION_ID}/undo`)) {
          return jsonResponse(sessionState({ canRedo: true }));
        }
        if (url.includes("/revisions?limit=50")) {
          return jsonResponse({ items: [], nextCursor: null });
        }
        return errorResponse("not_found", 404);
      }),
    );

    const { result } = actionsHook(readyEditorState(undefined, { canUndo: true }));
    dispatch(result.current.store, { type: "draft-adjustment", key: "contrast", value: 20 });

    await act(async () => {
      expect(await result.current.actions.undo()).toEqual({
        ok: false,
        revisionId: null,
      });
    });

    expect(urls.some((url) => url.endsWith("/undo"))).toBe(false);
    expect(result.current.store.state.draft.adjustments.contrast).toBe(20);
    expect(result.current.store.state.save.status).toBe("error");
  });

  it("reports nothing_to_undo without changing the session", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => errorResponse("nothing_to_undo", 409)),
    );
    const ready = readyEditorState();
    const { result } = actionsHook(ready);

    await act(async () => {
      expect(await result.current.actions.undo()).toEqual({
        ok: false,
        revisionId: null,
      });
    });

    expect(result.current.store.state.error?.code).toBe("nothing_to_undo");
    expect(result.current.store.state.committed).toEqual(ready.committed);
  });
});
