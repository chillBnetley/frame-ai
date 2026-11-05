import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useExport } from "@/features/editor/hooks/use-export";
import {
  EditorProvider,
  useEditorStore,
} from "@/features/editor/state/editor-context";
import type { EditorState } from "@/features/editor/state/editor-reducer";
import { REVISION_ID, SESSION_ID, readyEditorState } from "./session-fixtures";

function wrapperFor(initialState: EditorState) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <EditorProvider initialState={initialState}>{children}</EditorProvider>;
  };
}

function exportHook(initialState: EditorState) {
  return renderHook(
    () => ({ exporter: useExport(), store: useEditorStore() }),
    { wrapper: wrapperFor(initialState) },
  );
}

const originalCreateObjectURL = URL.createObjectURL;
const originalRevokeObjectURL = URL.revokeObjectURL;

afterEach(() => {
  vi.unstubAllGlobals();
  URL.createObjectURL = originalCreateObjectURL;
  URL.revokeObjectURL = originalRevokeObjectURL;
});

describe("useExport", () => {
  it("downloads the exported blob and revokes the object URL", async () => {
    const createObjectURL = vi.fn(() => "blob:frame-export");
    const revokeObjectURL = vi.fn();
    URL.createObjectURL = createObjectURL;
    URL.revokeObjectURL = revokeObjectURL;
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);

    const posted: Array<Record<string, unknown>> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith(`/api/v1/sessions/${SESSION_ID}/export`) && init?.method === "POST") {
          posted.push(JSON.parse(String(init.body)) as Record<string, unknown>);
          return new Response(new Blob(["jpeg-bytes"]), {
            status: 200,
            headers: {
              "content-type": "image/jpeg",
              "content-disposition": 'attachment; filename="frame-abcd1234.jpg"',
              "x-export-width": "240",
              "x-export-height": "320",
              "x-export-warning": "denoise_simplified",
            },
          });
        }
        return new Response("not found", { status: 404 });
      }),
    );

    const { result } = exportHook(readyEditorState());

    await act(async () => {
      expect(
        await result.current.exporter.exportImage({
          revisionId: REVISION_ID,
          format: "jpeg",
        }),
      ).toBe(true);
    });

    expect(posted).toEqual([{ revisionId: REVISION_ID, format: "jpeg" }]);
    expect(result.current.exporter.state.status).toBe("success");
    expect(result.current.exporter.state.filename).toBe("frame-abcd1234.jpg");
    expect(result.current.exporter.state.width).toBe(240);
    expect(result.current.exporter.state.height).toBe(320);
    expect(result.current.exporter.state.warnings).toEqual(["denoise_simplified"]);
    expect(click).toHaveBeenCalledTimes(1);
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(result.current.store.state.phase).toBe("ready");
    await waitFor(() => expect(revokeObjectURL).toHaveBeenCalledWith("blob:frame-export"));
  });

  it("forwards maxEdge and omits it when the original size is chosen", async () => {
    URL.createObjectURL = vi.fn(() => "blob:unused");
    URL.revokeObjectURL = vi.fn();
    const posted: Array<Record<string, unknown>> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith(`/api/v1/sessions/${SESSION_ID}/export`) && init?.method === "POST") {
          posted.push(JSON.parse(String(init.body)) as Record<string, unknown>);
          return new Response(new Blob(["jpeg-bytes"]), {
            status: 200,
            headers: {
              "content-type": "image/jpeg",
              "x-export-width": "240",
              "x-export-height": "320",
            },
          });
        }
        return new Response("not found", { status: 404 });
      }),
    );

    const { result } = exportHook(readyEditorState());

    await act(async () => {
      expect(
        await result.current.exporter.exportImage({
          revisionId: REVISION_ID,
          format: "jpeg",
          quality: 80,
          maxEdge: 2400,
        }),
      ).toBe(true);
    });
    await act(async () => {
      expect(
        await result.current.exporter.exportImage({
          revisionId: REVISION_ID,
          format: "jpeg",
          quality: 80,
          maxEdge: null,
        }),
      ).toBe(true);
    });

    expect(posted).toEqual([
      { revisionId: REVISION_ID, format: "jpeg", quality: 80, maxEdge: 2400 },
      { revisionId: REVISION_ID, format: "jpeg", quality: 80 },
    ]);
  });

  it("reports the estimated memory for export_too_large", async () => {
    URL.createObjectURL = vi.fn(() => "blob:unused");
    URL.revokeObjectURL = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            error: {
              code: "export_too_large",
              message: "too large",
              details: { estimatedPeakMb: 5643, limitMb: 3072, pixels: 24_000_000 },
            },
          }),
          { status: 413, headers: { "content-type": "application/json" } },
        ),
      ),
    );

    const { result } = exportHook(readyEditorState());

    await act(async () => {
      expect(
        await result.current.exporter.exportImage({
          revisionId: REVISION_ID,
          format: "jpeg",
        }),
      ).toBe(false);
    });

    expect(result.current.exporter.state.error?.message).toBe(
      "这张图在当前调整下导出需要约 5643 MB 内存，超过上限 3072 MB。可以减少调整项、选择更小的导出长边，或调高 FRAME_EXPORT_MAX_RSS_MB。",
    );
  });

  it("maps server_busy to a readable export error", async () => {
    URL.createObjectURL = vi.fn(() => "blob:unused");
    URL.revokeObjectURL = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({ error: { code: "server_busy", message: "busy", details: {} } }),
          { status: 503, headers: { "content-type": "application/json" } },
        ),
      ),
    );

    const { result } = exportHook(readyEditorState());

    await act(async () => {
      expect(
        await result.current.exporter.exportImage({
          revisionId: REVISION_ID,
          format: "png",
        }),
      ).toBe(false);
    });

    expect(result.current.exporter.state.status).toBe("error");
    expect(result.current.exporter.state.error?.message).toBe(
      "服务器内存不足或正在处理另一张高清导出，请稍后几秒再试。",
    );
    expect(result.current.store.state.phase).toBe("ready");
  });
});
