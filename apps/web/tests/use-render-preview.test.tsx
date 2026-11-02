import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useRenderPreview } from "@/features/editor/hooks/use-render-preview";
import {
  EditorProvider,
  useEditorStore,
} from "@/features/editor/state/editor-context";
import type { EditorAction, EditorState } from "@/features/editor/state/editor-reducer";
import { readyEditorState } from "./session-fixtures";

interface PendingRequest {
  body: Record<string, unknown>;
  signal: AbortSignal;
  resolve: (response: Response) => void;
}

function wrapperFor(initialState: EditorState) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <EditorProvider initialState={initialState}>{children}</EditorProvider>;
  };
}

function installRenderMock() {
  const pending: PendingRequest[] = [];
  const fetchMock = vi.fn(
    (_input: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((resolve) => {
        pending.push({
          body: JSON.parse(String(init?.body)) as Record<string, unknown>,
          signal: init?.signal as AbortSignal,
          resolve,
        });
      }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, pending };
}

function renderResponse(previewUrl: string, quality: "draft" | "final"): Response {
  return new Response(
    JSON.stringify({
      previewUrl,
      width: 1600,
      height: 1200,
      quality,
      cacheHit: false,
    }),
    { status: 200, headers: { "content-type": "application/json" } },
  );
}

async function flushMicrotasks(): Promise<void> {
  for (let index = 0; index < 8; index += 1) {
    await Promise.resolve();
  }
}

async function resolveRequest(
  pending: PendingRequest[],
  index: number,
  response: Response,
): Promise<void> {
  await act(async () => {
    pending[index]?.resolve(response);
    await flushMicrotasks();
  });
}

function hookFor(initialState: EditorState) {
  return renderHook(
    () => ({ renderer: useRenderPreview(), store: useEditorStore() }),
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

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useRenderPreview", () => {
  it("renders a final preview once a session becomes ready", async () => {
    const { fetchMock, pending } = installRenderMock();
    const { result } = hookFor(readyEditorState());

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(pending[0]?.body.quality).toBe("final");

    await resolveRequest(pending, 0, renderResponse("/previews/first", "final"));

    expect(result.current.store.state.preview.url).toBe("/previews/first");
    expect(result.current.store.state.preview.status).toBe("ready");
    expect(result.current.store.state.preview.width).toBe(1600);
  });

  it("debounces draft renders with a trailing 120ms timer", async () => {
    const { fetchMock, pending } = installRenderMock();
    const { result } = hookFor(readyEditorState());
    await resolveRequest(pending, 0, renderResponse("/previews/first", "final"));

    dispatch(result.current.store, { type: "draft-adjustment", key: "contrast", value: 10 });
    await act(async () => {
      vi.advanceTimersByTime(119);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(1);
      await flushMicrotasks();
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(pending[1]?.body.quality).toBe("draft");
  });

  it("aborts the previous request and keeps the newest preview", async () => {
    const { pending } = installRenderMock();
    const { result } = hookFor(readyEditorState());
    await resolveRequest(pending, 0, renderResponse("/previews/first", "final"));

    dispatch(result.current.store, { type: "draft-adjustment", key: "contrast", value: 10 });
    await act(async () => {
      vi.advanceTimersByTime(120);
      await flushMicrotasks();
    });

    dispatch(result.current.store, { type: "draft-adjustment", key: "contrast", value: 25 });
    await act(async () => {
      vi.advanceTimersByTime(120);
      await flushMicrotasks();
    });

    expect(pending).toHaveLength(3);
    expect(pending[1]?.signal.aborted).toBe(true);
    expect(pending[2]?.signal.aborted).toBe(false);

    await resolveRequest(pending, 2, renderResponse("/previews/latest", "draft"));
    expect(result.current.store.state.preview.url).toBe("/previews/latest");

    await resolveRequest(pending, 1, renderResponse("/previews/stale", "draft"));
    expect(result.current.store.state.preview.url).toBe("/previews/latest");
    expect(result.current.store.state.preview.status).toBe("ready");
  });

  it("sends an immediate final render on commit and cancels the pending debounce", async () => {
    const { fetchMock, pending } = installRenderMock();
    const { result } = hookFor(readyEditorState());
    await resolveRequest(pending, 0, renderResponse("/previews/first", "final"));

    dispatch(result.current.store, { type: "draft-adjustment", key: "contrast", value: 10 });
    act(() => {
      void result.current.renderer.requestFinal();
    });
    await act(async () => {
      await flushMicrotasks();
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(pending[1]?.body.quality).toBe("final");

    await act(async () => {
      vi.advanceTimersByTime(500);
      await flushMicrotasks();
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("surfaces render failures through the preview error state", async () => {
    const { pending } = installRenderMock();
    const { result } = hookFor(readyEditorState());

    await act(async () => {
      pending[0]?.resolve(
        new Response(
          JSON.stringify({
            error: { code: "storage_error", message: "boom", details: {} },
          }),
          { status: 500, headers: { "content-type": "application/json" } },
        ),
      );
      await flushMicrotasks();
    });

    expect(result.current.store.state.preview.status).toBe("error");
    expect(result.current.store.state.preview.error?.code).toBe("storage_error");
  });
});
