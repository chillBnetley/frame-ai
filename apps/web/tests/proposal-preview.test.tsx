import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  PREVIEW_DEBOUNCE_MS,
  useRenderPreview,
} from "@/features/editor/hooks/use-render-preview";
import {
  EditorProvider,
  useEditorStore,
} from "@/features/editor/state/editor-context";
import {
  editorReducer,
  type EditorState,
} from "@/features/editor/state/editor-reducer";
import { readyEditorState } from "./session-fixtures";
import { photographerPlan } from "./photographer-fixtures";

function wrapperFor(initialState: EditorState) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <EditorProvider initialState={initialState}>{children}</EditorProvider>;
  };
}

function installRenderMock() {
  const requests: Array<{ url: string; body: Record<string, unknown> }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      requests.push({
        url: String(input),
        body: JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>,
      });
      return new Response(
        JSON.stringify({
          previewUrl: `/previews/${requests.length}`,
          width: 1600,
          height: 1200,
          quality: (init?.body ? JSON.parse(String(init.body)).quality : "draft") as string,
          cacheHit: false,
          warnings: [],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }),
  );
  return requests;
}

function contrastOf(body: Record<string, unknown>): number | undefined {
  return (body.recipe as { adjustments?: { contrast?: number } } | undefined)
    ?.adjustments?.contrast;
}

function proposalState(): EditorState {
  return editorReducer(readyEditorState(), {
    type: "proposal-ready",
    plan: photographerPlan(),
  });
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useRenderPreview with a proposal", () => {
  it("renders the proposal recipe without touching the draft or session history", async () => {
    const requests = installRenderMock();
    const { result } = renderHook(
      () => ({ renderer: useRenderPreview(), store: useEditorStore() }),
      { wrapper: wrapperFor(proposalState()) },
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(requests).toHaveLength(1);
    expect(requests[0]?.url).toContain("/render");
    expect(requests[0]?.body.quality).toBe("final");
    expect(contrastOf(requests[0]?.body ?? {})).toBe(12);
    expect(result.current.store.state.draft.adjustments.contrast).toBe(0);
    expect(result.current.store.state.committed.adjustments.contrast).toBe(0);
    expect(result.current.store.state.proposal.status).toBe("ready");
    expect(requests.some((request) => request.url.includes("/revisions"))).toBe(false);
  });

  it("returns to the draft recipe when the user continues editing", async () => {
    const requests = installRenderMock();
    const { result } = renderHook(
      () => ({ renderer: useRenderPreview(), store: useEditorStore() }),
      { wrapper: wrapperFor(proposalState()) },
    );

    act(() => {
      result.current.store.dispatch({ type: "proposal-view", view: "editor" });
    });
    await act(async () => {
      vi.advanceTimersByTime(PREVIEW_DEBOUNCE_MS);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(requests).toHaveLength(2);
    expect(requests[1]?.body.quality).toBe("draft");
    expect(contrastOf(requests[1]?.body ?? {})).toBe(0);
    expect(result.current.store.state.proposal.status).toBe("ready");
  });
});
