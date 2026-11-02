import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EditorWorkspace } from "@/features/editor/editor-workspace";

const UPLOADED_IMAGE = {
  imageId: "2b1d0f76-4a1e-4de0-8a7b-3c0f2f9c1a55",
  originalName: "street.png",
  width: 800,
  height: 600,
  exifOrientation: 1,
  mimeType: "image/png",
  bytes: 2048,
};

const SESSION_STATE = {
  sessionId: "9d7c2a11-5b62-4f8e-9a41-0f3c7e6b2d18",
  imageId: UPLOADED_IMAGE.imageId,
  activeRevisionId: "6c0f4a92-3d15-4c8b-8f27-1a9e5b6d0c34",
  headRevisionId: "6c0f4a92-3d15-4c8b-8f27-1a9e5b6d0c34",
  canUndo: false,
  canRedo: false,
  revision: {
    id: "6c0f4a92-3d15-4c8b-8f27-1a9e5b6d0c34",
    revisionNo: 1,
    parentId: null,
    source: "initial",
    recipe: { schemaVersion: "1.0", styleId: "natural", styleStrength: 0 },
    createdAt: "2026-11-02T00:00:00Z",
  },
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

interface UploadErrorOption {
  code: string;
  message: string;
  status: number;
}

function mockApi(options: { uploadError?: UploadErrorOption } = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.endsWith("/api/v1/health")) {
      return jsonResponse({
        status: "ok",
        service: "FRAME AI API",
        version: "0.1.0",
        storage: { ok: true, writable: true },
      });
    }
    if (url.endsWith("/api/v1/config")) {
      return jsonResponse({
        maxUploadBytes: 20 * 1024 * 1024,
        maxImagePixels: 40_000_000,
        allowedMimeTypes: ["image/jpeg", "image/png", "image/webp"],
      });
    }
    if (url.endsWith("/api/v1/images") && init?.method === "POST") {
      if (options.uploadError) {
        return jsonResponse(
          {
            error: {
              code: options.uploadError.code,
              message: options.uploadError.message,
              details: {},
            },
          },
          options.uploadError.status,
        );
      }
      return jsonResponse(UPLOADED_IMAGE, 201);
    }
    if (url.endsWith("/api/v1/sessions") && init?.method === "POST") {
      return jsonResponse(SESSION_STATE, 201);
    }
    if (url.includes(`/api/v1/sessions/${SESSION_STATE.sessionId}/revisions`)) {
      return jsonResponse({ items: [], nextCursor: null });
    }
    if (url.endsWith(`/api/v1/sessions/${SESSION_STATE.sessionId}/render`)) {
      return jsonResponse({
        previewUrl: "/api/v1/previews/mocked-preview",
        width: 800,
        height: 600,
        quality: "final",
        cacheHit: false,
      });
    }
    return jsonResponse({ error: { code: "not_found", message: "Not found", details: {} } }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function mockSlowUpload() {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.endsWith("/api/v1/health")) {
      return Promise.resolve(
        jsonResponse({
          status: "ok",
          service: "FRAME AI API",
          version: "0.1.0",
          storage: { ok: true, writable: true },
        }),
      );
    }
    if (url.endsWith("/api/v1/config")) {
      return Promise.resolve(
        jsonResponse({
          maxUploadBytes: 20 * 1024 * 1024,
          maxImagePixels: 40_000_000,
          allowedMimeTypes: ["image/jpeg", "image/png", "image/webp"],
        }),
      );
    }
    if (url.endsWith("/api/v1/images") && init?.method === "POST") {
      return new Promise<Response>((_resolve, reject) => {
        init.signal?.addEventListener("abort", () => {
          reject(new DOMException("Aborted", "AbortError"));
        });
      });
    }
    return Promise.resolve(
      jsonResponse({ error: { code: "not_found", message: "Not found", details: {} } }, 404),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function uploadFile() {
  const input = screen.getByTestId("file-input");
  const file = new File([new Uint8Array([1, 2, 3, 4])], "street.png", { type: "image/png" });
  await userEvent.upload(input, file);
}

beforeEach(() => {
  window.history.replaceState({}, "", "/");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("EditorWorkspace", () => {
  it("uploads a photo and enters the editor with a server-rendered preview", async () => {
    const fetchMock = mockApi();
    render(<EditorWorkspace />);

    expect(await screen.findByText("API 已连接")).toBeInTheDocument();
    expect(screen.getByText("拖入一张照片")).toBeInTheDocument();

    await uploadFile();

    expect(await screen.findByText("编辑预览")).toBeInTheDocument();
    expect(await screen.findByAltText("编辑后的预览")).toBeInTheDocument();
    expect(screen.getAllByText("800 × 600").length).toBeGreaterThan(0);
    expect(screen.getByText("手动参数")).toBeInTheDocument();
    expect(screen.getByText("历史与版本")).toBeInTheDocument();
    expect(window.location.search).toBe(`?session=${SESSION_STATE.sessionId}`);

    const download = screen.getByRole("link", { name: /下载原图/ });
    expect(download).toHaveAttribute(
      "href",
      `/api/v1/images/${UPLOADED_IMAGE.imageId}/original?download=true`,
    );
    expect(download).toHaveAttribute("download", "street.png");

    const uploadCall = fetchMock.mock.calls.find(
      ([input, init]) =>
        typeof input === "string" &&
        input.endsWith("/api/v1/images") &&
        (init as RequestInit | undefined)?.method === "POST",
    );
    expect(uploadCall).toBeTruthy();
    expect((uploadCall?.[1] as RequestInit).body).toBeInstanceOf(FormData);
  });

  it("shows a readable error when the server rejects the file", async () => {
    mockApi({
      uploadError: {
        code: "unsupported_media_type",
        message: "Only JPEG, PNG, and WebP images are supported.",
        status: 415,
      },
    });
    render(<EditorWorkspace />);

    await screen.findByText("API 已连接");
    await uploadFile();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("仅支持 JPEG、PNG 与 WebP 图片。");
    expect(alert).toHaveTextContent("unsupported_media_type");
    expect(screen.queryByRole("button", { name: "重试上传" })).not.toBeInTheDocument();
  });

  it("offers retry for transient server failures", async () => {
    mockApi({
      uploadError: {
        code: "storage_error",
        message: "The image could not be registered.",
        status: 500,
      },
    });
    render(<EditorWorkspace />);

    await screen.findByText("API 已连接");
    await uploadFile();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("原图保存失败，请稍后重试。");
    expect(screen.getByRole("button", { name: "重试上传" })).toBeInTheDocument();
  });

  it("cancels an in-flight upload and returns to the empty state", async () => {
    mockSlowUpload();
    render(<EditorWorkspace />);

    await screen.findByText("API 已连接");
    await uploadFile();

    const cancel = await screen.findByRole("button", { name: "取消上传" });
    await userEvent.click(cancel);

    expect(await screen.findByText("拖入一张照片")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "取消上传" })).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
