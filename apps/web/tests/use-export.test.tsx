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

const JOB_ID = "job-1234";
const CREATED_AT = "2026-11-07T00:00:00.000Z";

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

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function jobPayload(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    jobId: JOB_ID,
    status: "queued",
    filename: null,
    width: null,
    height: null,
    bitDepth: 8,
    warnings: [],
    error: null,
    createdAt: CREATED_AT,
    updatedAt: CREATED_AT,
    ...overrides,
  };
}

function resultResponse(): Response {
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

const originalCreateObjectURL = URL.createObjectURL;
const originalRevokeObjectURL = URL.revokeObjectURL;

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  URL.createObjectURL = originalCreateObjectURL;
  URL.revokeObjectURL = originalRevokeObjectURL;
});

describe("useExport", () => {
  it("submits a job, polls it and downloads the result blob", async () => {
    const createObjectURL = vi.fn(() => "blob:frame-export");
    const revokeObjectURL = vi.fn();
    URL.createObjectURL = createObjectURL;
    URL.revokeObjectURL = revokeObjectURL;
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);

    const posted: Array<Record<string, unknown>> = [];
    let statusPolls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/v1/exports") && init?.method === "POST") {
          posted.push(JSON.parse(String(init.body)) as Record<string, unknown>);
          return jsonResponse(jobPayload(), 202);
        }
        if (url.endsWith(`/api/v1/exports/${JOB_ID}/result`)) {
          return resultResponse();
        }
        if (url.endsWith(`/api/v1/exports/${JOB_ID}`)) {
          statusPolls += 1;
          return jsonResponse(
            jobPayload({
              status: "succeeded",
              filename: "frame-abcd1234.jpg",
              width: 240,
              height: 320,
              warnings: ["denoise_simplified"],
            }),
          );
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

    expect(posted).toEqual([
      { sessionId: SESSION_ID, revisionId: REVISION_ID, format: "jpeg", bitDepth: 8 },
    ]);
    expect(statusPolls).toBe(1);
    expect(result.current.exporter.state.status).toBe("success");
    expect(result.current.exporter.state.filename).toBe("frame-abcd1234.jpg");
    expect(result.current.exporter.state.width).toBe(240);
    expect(result.current.exporter.state.height).toBe(320);
    expect(result.current.exporter.state.bytes).toBeGreaterThan(0);
    expect(result.current.exporter.state.warnings).toEqual(["denoise_simplified"]);
    expect(click).toHaveBeenCalledTimes(1);
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(result.current.store.state.phase).toBe("ready");
    await waitFor(() => expect(revokeObjectURL).toHaveBeenCalledWith("blob:frame-export"));
  });

  it("forwards maxEdge and omits it when the original size is chosen", async () => {
    URL.createObjectURL = vi.fn(() => "blob:unused");
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    const posted: Array<Record<string, unknown>> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/v1/exports") && init?.method === "POST") {
          posted.push(JSON.parse(String(init.body)) as Record<string, unknown>);
          return jsonResponse(jobPayload(), 202);
        }
        if (url.endsWith(`/api/v1/exports/${JOB_ID}/result`)) {
          return resultResponse();
        }
        if (url.endsWith(`/api/v1/exports/${JOB_ID}`)) {
          return jsonResponse(
            jobPayload({
              status: "succeeded",
              filename: "frame-abcd1234.jpg",
              width: 240,
              height: 320,
            }),
          );
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
      {
        sessionId: SESSION_ID,
        revisionId: REVISION_ID,
        format: "jpeg",
        bitDepth: 8,
        quality: 80,
        maxEdge: 2400,
      },
      {
        sessionId: SESSION_ID,
        revisionId: REVISION_ID,
        format: "jpeg",
        bitDepth: 8,
        quality: 80,
      },
    ]);
  });

  it("sends bitDepth 16 for a 16-bit PNG export", async () => {
    URL.createObjectURL = vi.fn(() => "blob:png16");
    URL.revokeObjectURL = vi.fn();
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);

    const posted: Array<Record<string, unknown>> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/v1/exports") && init?.method === "POST") {
          posted.push(JSON.parse(String(init.body)) as Record<string, unknown>);
          return jsonResponse(jobPayload({ bitDepth: 16 }), 202);
        }
        if (url.endsWith(`/api/v1/exports/${JOB_ID}/result`)) {
          return new Response(new Blob(["png-bytes"]), {
            status: 200,
            headers: {
              "content-type": "image/png",
              "content-disposition": 'attachment; filename="frame-abcd1234.png"',
              "x-export-width": "640",
              "x-export-height": "480",
              "x-export-bit-depth": "16",
            },
          });
        }
        if (url.endsWith(`/api/v1/exports/${JOB_ID}`)) {
          return jsonResponse(
            jobPayload({
              status: "succeeded",
              filename: "frame-abcd1234.png",
              width: 640,
              height: 480,
              bitDepth: 16,
            }),
          );
        }
        return new Response("not found", { status: 404 });
      }),
    );

    const { result } = exportHook(readyEditorState());

    await act(async () => {
      expect(
        await result.current.exporter.exportImage({
          revisionId: REVISION_ID,
          format: "png",
          bitDepth: 16,
        }),
      ).toBe(true);
    });

    expect(posted).toEqual([
      {
        sessionId: SESSION_ID,
        revisionId: REVISION_ID,
        format: "png",
        bitDepth: 16,
      },
    ]);
    expect(result.current.exporter.state.status).toBe("success");
    expect(result.current.exporter.state.filename).toBe("frame-abcd1234.png");
    expect(click).toHaveBeenCalledTimes(1);
  });

  it("reports the estimated memory when the job fails with export_too_large", async () => {
    URL.createObjectURL = vi.fn(() => "blob:unused");
    URL.revokeObjectURL = vi.fn();
    const downloaded = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/v1/exports") && init?.method === "POST") {
          return jsonResponse(jobPayload(), 202);
        }
        if (url.endsWith(`/api/v1/exports/${JOB_ID}/result`)) {
          downloaded();
          return resultResponse();
        }
        if (url.endsWith(`/api/v1/exports/${JOB_ID}`)) {
          return jsonResponse(
            jobPayload({
              status: "failed",
              error: {
                code: "export_too_large",
                message: "too large",
                details: { estimatedPeakMb: 5643, limitMb: 3072, pixels: 24_000_000 },
              },
            }),
          );
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
      ).toBe(false);
    });

    expect(result.current.exporter.state.status).toBe("error");
    expect(result.current.exporter.state.error?.code).toBe("export_too_large");
    expect(result.current.exporter.state.error?.message).toBe(
      "这张图在当前调整下导出需要约 5643 MB 内存，超过上限 3072 MB。可以减少调整项、选择更小的导出长边，或调高 FRAME_EXPORT_MAX_RSS_MB。",
    );
    expect(downloaded).not.toHaveBeenCalled();
    expect(result.current.store.state.phase).toBe("ready");
  });

  it("maps a full queue (server_busy) to a readable export error", async () => {
    URL.createObjectURL = vi.fn(() => "blob:unused");
    URL.revokeObjectURL = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(
          { error: { code: "server_busy", message: "busy", details: {} } },
          503,
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

  it("cancels a running job, stops polling and releases the editor", async () => {    URL.createObjectURL = vi.fn(() => "blob:unused");
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    let statusPolls = 0;
    const cancelled: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/v1/exports") && init?.method === "POST") {
          return jsonResponse(jobPayload(), 202);
        }
        if (url.endsWith(`/api/v1/exports/${JOB_ID}`) && init?.method === "DELETE") {
          cancelled.push(JOB_ID);
          return new Response(null, { status: 204 });
        }
        if (url.endsWith(`/api/v1/exports/${JOB_ID}`)) {
          statusPolls += 1;
          return jsonResponse(jobPayload({ status: "running" }));
        }
        return new Response("not found", { status: 404 });
      }),
    );

    const { result } = exportHook(readyEditorState());

    let outcome: Promise<boolean> | null = null;
    act(() => {
      outcome = result.current.exporter.exportImage({
        revisionId: REVISION_ID,
        format: "jpeg",
      });
    });

    await waitFor(() => expect(statusPolls).toBeGreaterThan(0));
    expect(result.current.exporter.state.status).toBe("exporting");

    await act(async () => {
      await result.current.exporter.cancel();
    });

    expect(await outcome).toBe(false);
    expect(cancelled).toEqual([JOB_ID]);
    expect(statusPolls).toBe(1);
    expect(result.current.exporter.state.status).toBe("cancelled");
    expect(result.current.exporter.state.error).toBeNull();
    expect(result.current.store.state.phase).toBe("ready");
  });

  it("sends DELETE for the active job when the hook unmounts", async () => {
    URL.createObjectURL = vi.fn(() => "blob:unused");
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    let statusPolls = 0;
    const cancelled: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/v1/exports") && init?.method === "POST") {
          return jsonResponse(jobPayload(), 202);
        }
        if (url.endsWith(`/api/v1/exports/${JOB_ID}`) && init?.method === "DELETE") {
          cancelled.push(JOB_ID);
          return new Response(null, { status: 204 });
        }
        if (url.endsWith(`/api/v1/exports/${JOB_ID}`)) {
          statusPolls += 1;
          return jsonResponse(jobPayload({ status: "running" }));
        }
        return new Response("not found", { status: 404 });
      }),
    );

    const { result, unmount } = exportHook(readyEditorState());

    act(() => {
      void result.current.exporter.exportImage({
        revisionId: REVISION_ID,
        format: "jpeg",
      });
    });
    await waitFor(() => expect(statusPolls).toBeGreaterThan(0));

    unmount();

    await waitFor(() => expect(cancelled).toEqual([JOB_ID]));
  });
});
