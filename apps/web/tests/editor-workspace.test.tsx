import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EditorWorkspace } from "@/features/editor/editor-workspace";
import { analysisReport, analysisStatus, ANALYSIS_ID } from "./analysis-fixtures";

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
    recipe: { schemaVersion: "2.0", styleId: "natural", styleStrength: 0 },
    createdAt: "2026-11-02T00:00:00Z",
  },
};

function jsonResponse(
  body: unknown,
  status = 200,
  headers: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

interface UploadErrorOption {
  code: string;
  message: string;
  status: number;
}

interface SessionErrorOption extends UploadErrorOption {
  requestId?: string;
}

interface MockApiOptions {
  layers?: boolean;
  uploadError?: UploadErrorOption;
  sessionError?: SessionErrorOption;
  revisionError?: UploadErrorOption;
  revisionGate?: Promise<void>;
  renderError?: UploadErrorOption;
  renderErrorOnce?: UploadErrorOption;
  deleteError?: UploadErrorOption;
}

function reportForUploadedImage() {
  const base = analysisReport();
  return analysisReport({
    image: {
      ...base.image,
      id: UPLOADED_IMAGE.imageId,
      width: UPLOADED_IMAGE.width,
      height: UPLOADED_IMAGE.height,
      aspectRatio: UPLOADED_IMAGE.width / UPLOADED_IMAGE.height,
    },
  });
}

function mockApi(options: MockApiOptions = {}) {
  let revisionCount = 0;
  let lastRevisionId = SESSION_STATE.activeRevisionId;
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
        features: { layers: options.layers === true },
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
    if (
      url.endsWith(`/api/v1/images/${UPLOADED_IMAGE.imageId}`) &&
      init?.method === "DELETE"
    ) {
      if (options.deleteError) {
        return jsonResponse(
          {
            error: {
              code: options.deleteError.code,
              message: options.deleteError.message,
              details: {},
            },
          },
          options.deleteError.status,
        );
      }
      return new Response(null, { status: 204 });
    }
    if (url.endsWith("/api/v1/sessions") && init?.method === "POST") {
      if (options.sessionError) {
        return jsonResponse(
          {
            error: {
              code: options.sessionError.code,
              message: options.sessionError.message,
              details: {},
            },
          },
          options.sessionError.status,
          options.sessionError.requestId
            ? { "x-request-id": options.sessionError.requestId }
            : {},
        );
      }
      return jsonResponse(SESSION_STATE, 201);
    }
    if (
      url.endsWith(`/api/v1/sessions/${SESSION_STATE.sessionId}/revisions`) &&
      init?.method === "POST"
    ) {
      revisionCount += 1;
      const body = JSON.parse(String(init.body)) as { recipe: unknown };
      if (options.revisionError) {
        return jsonResponse(
          {
            error: {
              code: options.revisionError.code,
              message: options.revisionError.message,
              details: {},
            },
          },
          options.revisionError.status,
        );
      }
      if (options.revisionGate && revisionCount === 1) {
        await options.revisionGate;
      }
      const revisionId = `7f2e5c31-9a4b-4d6e-8c10-${String(revisionCount).padStart(12, "0")}`;
      const response = {
        ...SESSION_STATE,
        activeRevisionId: revisionId,
        headRevisionId: revisionId,
        canUndo: true,
        revision: {
          ...SESSION_STATE.revision,
          id: revisionId,
          revisionNo: revisionCount + 1,
          parentId: lastRevisionId,
          source: "user",
          recipe: body.recipe,
        },
      };
      lastRevisionId = revisionId;
      return jsonResponse(response, 201);
    }
    if (url.includes(`/api/v1/sessions/${SESSION_STATE.sessionId}/revisions`)) {
      return jsonResponse({ items: [], nextCursor: null });
    }
    if (url.endsWith(`/api/v1/sessions/${SESSION_STATE.sessionId}/render`)) {
      const renderError = options.renderError ?? options.renderErrorOnce;
      if (renderError) {
        options.renderErrorOnce = undefined;
        return jsonResponse(
          {
            error: {
              code: renderError.code,
              message: renderError.message,
              details: {},
            },
          },
          renderError.status,
        );
      }
      return jsonResponse({
        previewUrl: "/api/v1/previews/mocked-preview",
        width: 800,
        height: 600,
        quality: "final",
        cacheHit: false,
      });
    }
    if (url.endsWith("/api/v1/analysis") && init?.method === "POST") {
      return jsonResponse(
        {
          analysisId: ANALYSIS_ID,
          status: "pending",
          stage: "queued",
          deduplicated: false,
        },
        202,
      );
    }
    if (url.endsWith(`/api/v1/analysis/${ANALYSIS_ID}/result`)) {
      return jsonResponse(reportForUploadedImage());
    }
    if (url.endsWith(`/api/v1/analysis/${ANALYSIS_ID}`)) {
      return jsonResponse(
        analysisStatus({
          status: "completed",
          stage: "completed",
          resultAvailable: true,
          result: reportForUploadedImage(),
        }),
      );
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
          features: { layers: false },
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

type FetchMock = ReturnType<typeof mockApi>;

function callCount(fetchMock: FetchMock, suffix: string, method?: string): number {
  return fetchMock.mock.calls.filter(([input, init]) => {
    if (typeof input !== "string" || !input.endsWith(suffix)) {
      return false;
    }
    return method === undefined || (init as RequestInit | undefined)?.method === method;
  }).length;
}

function revisionBodies(
  fetchMock: FetchMock,
): Array<{
  recipe: {
    adjustments?: { exposureEv?: number };
    curve?: { master?: Array<{ x: number; y: number }> };
    hsl?: {
      blue?: { hue?: number; saturation?: number; luminance?: number };
    };
    colorGrading?: {
      shadows?: { hue?: number; saturation?: number };
      midtones?: { hue?: number; saturation?: number };
      highlights?: { hue?: number; saturation?: number };
      balance?: number;
      blending?: number;
    };
    masks?: Array<{
      id: string;
      shape: string;
      feather: number;
      opacity: number;
      inverted: boolean;
    }>;
    localAdjustments?: Array<{
      id: string;
      maskId: string;
      enabled: boolean;
      adjustments: { exposureEv?: number };
    }>;
  };
}> {
  return fetchMock.mock.calls
    .filter(
      ([input, init]) =>
        typeof input === "string" &&
        input.endsWith(`/api/v1/sessions/${SESSION_STATE.sessionId}/revisions`) &&
        (init as RequestInit | undefined)?.method === "POST",
    )
    .map(([, init]) => JSON.parse(String((init as RequestInit).body)));
}

beforeEach(() => {
  window.history.replaceState({}, "", "/");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
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

  it("deletes the photo after confirmation and returns to the upload state", async () => {
    const fetchMock = mockApi();
    render(<EditorWorkspace />);

    expect(await screen.findByText("API 已连接")).toBeInTheDocument();
    await uploadFile();
    expect(await screen.findByText("编辑预览")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "删除照片" }));
    expect(
      screen.getByRole("dialog", { name: "删除这张照片？" }),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "永久删除" }));

    expect(
      await screen.findByText(
        "照片及其编辑会话、分析与缓存副本已从本机永久删除。",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("拖入一张照片")).toBeInTheDocument();
    expect(window.location.search).toBe("");
    expect(
      callCount(fetchMock, `/api/v1/images/${UPLOADED_IMAGE.imageId}`, "DELETE"),
    ).toBe(1);
  });

  it("keeps the editor and explains a busy delete", async () => {
    mockApi({
      deleteError: {
        code: "resource_busy",
        message: "The image is in use by a running analysis or export.",
        status: 409,
      },
    });
    render(<EditorWorkspace />);

    await screen.findByText("API 已连接");
    await uploadFile();
    expect(await screen.findByText("编辑预览")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "删除照片" }));
    await userEvent.click(screen.getByRole("button", { name: "永久删除" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "这张照片正在分析或导出，完成后再删除。",
    );
    expect(screen.getByText("编辑预览")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "永久删除" }),
    ).toBeEnabled();
  });

  it("opens the analysis panel and renders a completed report", async () => {
    const fetchMock = mockApi();
    render(<EditorWorkspace />);

    expect(await screen.findByText("API 已连接")).toBeInTheDocument();
    await uploadFile();
    expect(await screen.findByText("编辑预览")).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: /AI 摄影分析/ }),
    );
    expect(
      screen.getByRole("heading", { name: "AI 摄影分析" }),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "开始分析" }));

    expect(
      await screen.findByRole("heading", { name: "场景识别" }, { timeout: 3000 }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("模拟分析（未调用真实视觉模型）"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "AI 摄影建议" }),
    ).toBeInTheDocument();

    const createCall = fetchMock.mock.calls.find(
      ([input, init]) =>
        typeof input === "string" &&
        input.endsWith("/api/v1/analysis") &&
        (init as RequestInit | undefined)?.method === "POST",
    );
    expect(createCall).toBeTruthy();
    expect(JSON.parse(String((createCall?.[1] as RequestInit).body))).toEqual({
      imageId: UPLOADED_IMAGE.imageId,
      force: false,
    });
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
    expect(alert).toHaveTextContent("仅支持 JPEG、PNG、WebP 与 TIFF 图片。");
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

  it("labels session failures and retries without uploading the photo again", async () => {
    const requestId = "27cd3e6046ba4d9b9a8b5f0eec41fa08";
    const fetchMock = mockApi({
      sessionError: {
        code: "internal_error",
        message: "Unexpected failure",
        status: 500,
        requestId,
      },
    });
    render(<EditorWorkspace />);

    await screen.findByText("API 已连接");
    await uploadFile();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("服务出现未预期错误，请稍后重试。");
    expect(alert).toHaveTextContent("创建编辑会话");
    expect(alert).toHaveTextContent("internal_error");
    expect(alert).toHaveTextContent(requestId);
    expect(screen.getByText("street.png")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "重试创建会话" }));

    await waitFor(() => {
      const sessionCalls = fetchMock.mock.calls.filter(
        ([input, init]) =>
          typeof input === "string" &&
          input.endsWith("/api/v1/sessions") &&
          (init as RequestInit | undefined)?.method === "POST",
      );
      expect(sessionCalls).toHaveLength(2);
    });
    const uploadCalls = fetchMock.mock.calls.filter(
      ([input, init]) =>
        typeof input === "string" &&
        input.endsWith("/api/v1/images") &&
        (init as RequestInit | undefined)?.method === "POST",
    );
    expect(uploadCalls).toHaveLength(1);
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

  it("does not save or re-render while tabbing through untouched sliders", async () => {
    const fetchMock = mockApi();
    render(<EditorWorkspace />);

    await screen.findByText("API 已连接");
    await uploadFile();
    await screen.findByAltText("编辑后的预览");
    await waitFor(() => {
      expect(callCount(fetchMock, "/render")).toBeGreaterThan(0);
    });

    const rendersBefore = callCount(fetchMock, "/render");
    const revisionsBefore = callCount(fetchMock, "/revisions", "POST");

    screen.getByRole("slider", { name: "曝光" }).focus();
    for (let step = 0; step < 32; step += 1) {
      await userEvent.tab();
    }
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(callCount(fetchMock, "/render")).toBe(rendersBefore);
    expect(callCount(fetchMock, "/revisions", "POST")).toBe(revisionsBefore);
  });

  it("retries the crop base once when a newer render supersedes it", async () => {
    const options: MockApiOptions = {};
    const fetchMock = mockApi(options);
    render(<EditorWorkspace />);

    await screen.findByText("API 已连接");
    await uploadFile();
    await screen.findByAltText("编辑后的预览");

    const rendersBefore = callCount(fetchMock, "/render");
    options.renderErrorOnce = {
      code: "render_superseded",
      message: "A newer render request replaced this one.",
      status: 409,
    };

    await userEvent.click(screen.getByRole("button", { name: "裁切" }));

    expect(await screen.findByAltText("裁切基准画面")).toBeInTheDocument();
    expect(callCount(fetchMock, "/render")).toBe(rendersBefore + 2);
    expect(screen.queryByText("操作未完成，请重试。")).not.toBeInTheDocument();
  });

  it("shows a non-empty crop base error when the retry is also superseded", async () => {
    const options: MockApiOptions = {};
    const fetchMock = mockApi(options);
    render(<EditorWorkspace />);

    await screen.findByText("API 已连接");
    await uploadFile();
    await screen.findByAltText("编辑后的预览");

    options.renderError = {
      code: "render_superseded",
      message: "A newer render request replaced this one.",
      status: 409,
    };
    const rendersBefore = callCount(fetchMock, "/render");

    await userEvent.click(screen.getByRole("button", { name: "裁切" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("操作未完成，请重试。");
    expect(callCount(fetchMock, "/render")).toBe(rendersBefore + 2);

    options.renderError = undefined;
    await userEvent.click(
      screen.getByRole("button", { name: "重新获取裁切基准" }),
    );
    expect(await screen.findByAltText("裁切基准画面")).toBeInTheDocument();
  });

  it("keeps adjusting while saving and merges the latest draft into a follow-up save", async () => {
    let releaseFirstSave!: () => void;
    const revisionGate = new Promise<void>((resolve) => {
      releaseFirstSave = resolve;
    });
    const fetchMock = mockApi({ revisionGate });
    render(<EditorWorkspace />);

    await screen.findByText("API 已连接");
    await uploadFile();
    await screen.findByAltText("编辑后的预览");

    const slider = screen.getByRole("slider", { name: "曝光" });
    fireEvent.change(slider, { target: { value: "1" } });
    fireEvent.pointerUp(slider);

    await waitFor(() => {
      expect(callCount(fetchMock, "/revisions", "POST")).toBe(1);
    });
    expect(await screen.findByText("保存中…")).toBeInTheDocument();
    expect(slider).toBeEnabled();
    expect(screen.getByRole("slider", { name: "对比度" })).toBeEnabled();

    fireEvent.change(slider, { target: { value: "2" } });
    fireEvent.pointerUp(slider);
    releaseFirstSave();

    await waitFor(() => {
      expect(callCount(fetchMock, "/revisions", "POST")).toBe(2);
    });
    expect(await screen.findByText("已保存")).toBeInTheDocument();

    const bodies = revisionBodies(fetchMock);
    expect(bodies).toHaveLength(2);
    expect(bodies[1]?.recipe.adjustments?.exposureEv).toBe(2);
  });

  it("lets the user discard the draft after a failed save", async () => {
    mockApi({
      revisionError: {
        code: "storage_error",
        message: "The revision could not be stored.",
        status: 500,
      },
    });
    render(<EditorWorkspace />);

    await screen.findByText("API 已连接");
    await uploadFile();
    await screen.findByAltText("编辑后的预览");

    const slider = screen.getByRole("slider", { name: "曝光" });
    fireEvent.change(slider, { target: { value: "1.5" } });
    fireEvent.pointerUp(slider);

    const discard = await screen.findByRole("button", { name: "放弃未保存调整" });
    expect(screen.getByText("保存失败")).toBeInTheDocument();

    await userEvent.click(discard);

    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: "放弃未保存调整" }),
      ).not.toBeInTheDocument();
    });
    expect(screen.getByText("已保存")).toBeInTheDocument();
    expect(screen.getByRole("slider", { name: "曝光" })).toHaveValue("0");
  });

  it("adds curve nodes to the draft, re-renders, and saves them", async () => {
    const fetchMock = mockApi();
    render(<EditorWorkspace />);

    await screen.findByText("API 已连接");
    await uploadFile();
    await screen.findByAltText("编辑后的预览");
    await waitFor(() => {
      expect(callCount(fetchMock, "/render")).toBeGreaterThan(0);
    });

    vi.spyOn(SVGSVGElement.prototype, "getBoundingClientRect").mockReturnValue({
      left: 0,
      top: 0,
      right: 100,
      bottom: 100,
      width: 100,
      height: 100,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);

    const rendersBefore = callCount(fetchMock, "/render");
    fireEvent.click(screen.getByTestId("curve-surface"), {
      clientX: 50,
      clientY: 50,
    });

    await waitFor(() => {
      expect(callCount(fetchMock, "/revisions", "POST")).toBe(1);
    });
    expect(callCount(fetchMock, "/render")).toBeGreaterThan(rendersBefore);

    const [body] = revisionBodies(fetchMock);
    expect(body?.recipe.curve?.master).toHaveLength(3);
    expect(body?.recipe.curve?.master?.[1]?.x).toBeCloseTo(0.5, 6);
    expect(screen.getByTestId("curve-node-1")).toBeInTheDocument();
  });

  it("edits an HSL band, re-renders, and saves it", async () => {
    const fetchMock = mockApi();
    render(<EditorWorkspace />);

    await screen.findByText("API 已连接");
    await uploadFile();
    await screen.findByAltText("编辑后的预览");
    await waitFor(() => {
      expect(callCount(fetchMock, "/render")).toBeGreaterThan(0);
    });

    const rendersBefore = callCount(fetchMock, "/render");
    await userEvent.click(screen.getByRole("button", { name: "蓝色" }));
    const hue = screen.getByRole("slider", { name: "蓝色 色相" });
    fireEvent.change(hue, { target: { value: "20" } });
    fireEvent.pointerUp(hue);

    await waitFor(() => {
      expect(callCount(fetchMock, "/revisions", "POST")).toBe(1);
    });
    expect(callCount(fetchMock, "/render")).toBeGreaterThan(rendersBefore);

    const [body] = revisionBodies(fetchMock);
    expect(body?.recipe.hsl?.blue?.hue).toBe(20);
    expect(screen.getByRole("slider", { name: "蓝色 色相" })).toHaveValue("20");
  });

  it("edits a grading zone, re-renders, and saves it", async () => {
    const fetchMock = mockApi();
    render(<EditorWorkspace />);

    await screen.findByText("API 已连接");
    await uploadFile();
    await screen.findByAltText("编辑后的预览");
    await waitFor(() => {
      expect(callCount(fetchMock, "/render")).toBeGreaterThan(0);
    });

    const rendersBefore = callCount(fetchMock, "/render");
    await userEvent.click(screen.getByRole("button", { name: "阴影" }));
    const hue = screen.getByRole("slider", { name: "阴影 色相" });
    fireEvent.change(hue, { target: { value: "220" } });
    fireEvent.pointerUp(hue);

    await waitFor(() => {
      expect(callCount(fetchMock, "/revisions", "POST")).toBe(1);
    });

    const strength = screen.getByRole("slider", { name: "阴影 强度" });
    fireEvent.change(strength, { target: { value: "30" } });
    fireEvent.pointerUp(strength);

    await waitFor(() => {
      expect(callCount(fetchMock, "/revisions", "POST")).toBeGreaterThan(1);
    });
    expect(callCount(fetchMock, "/render")).toBeGreaterThan(rendersBefore);

    const bodies = revisionBodies(fetchMock);
    const latest = bodies[bodies.length - 1];
    expect(latest?.recipe.colorGrading?.shadows?.hue).toBe(220);
    expect(latest?.recipe.colorGrading?.shadows?.saturation).toBe(30);
  });

  it("creates a local mask, re-renders, and saves the local adjustment", async () => {
    const fetchMock = mockApi();
    render(<EditorWorkspace />);

    await screen.findByText("API 已连接");
    await uploadFile();
    await screen.findByAltText("编辑后的预览");
    await waitFor(() => {
      expect(callCount(fetchMock, "/render")).toBeGreaterThan(0);
    });

    await userEvent.click(screen.getByRole("button", { name: "添加矩形区域" }));
    await waitFor(() => {
      expect(callCount(fetchMock, "/revisions", "POST")).toBe(1);
    });

    const exposure = screen.getByRole("slider", { name: "局部曝光" });
    fireEvent.change(exposure, { target: { value: "0.75" } });
    fireEvent.pointerUp(exposure);
    await waitFor(() => {
      expect(callCount(fetchMock, "/revisions", "POST")).toBe(2);
    });

    const feather = screen.getByRole("slider", { name: "局部羽化" });
    fireEvent.change(feather, { target: { value: "35" } });
    fireEvent.pointerUp(feather);
    await waitFor(() => {
      expect(callCount(fetchMock, "/revisions", "POST")).toBe(3);
    });

    const bodies = revisionBodies(fetchMock);
    const latest = bodies[bodies.length - 1];
    expect(latest?.recipe.masks).toHaveLength(1);
    expect(latest?.recipe.masks?.[0]?.shape).toBe("rectangle");
    expect(latest?.recipe.masks?.[0]?.feather).toBe(35);
    expect(latest?.recipe.localAdjustments).toHaveLength(1);
    expect(latest?.recipe.localAdjustments?.[0]?.maskId).toBe(
      latest?.recipe.masks?.[0]?.id,
    );
    expect(latest?.recipe.localAdjustments?.[0]?.adjustments.exposureEv).toBe(
      0.75,
    );
    expect(screen.getByTestId("mask-outline")).toBeInTheDocument();
  });
});

describe("EditorWorkspace layer feature gate", () => {
  it("shows layer controls when the runtime config enables layers", async () => {
    mockApi({ layers: true });
    render(<EditorWorkspace />);

    expect(await screen.findByText("API 已连接")).toBeInTheDocument();
    await uploadFile();
    expect(await screen.findByText("编辑预览")).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "添加全图局部调整" }),
    );

    expect(await screen.findByRole("combobox", { name: "混合模式 1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "上移图层 1" })).toBeDisabled();
    expect(screen.getByRole("spinbutton", { name: "图层不透明度" })).toBeInTheDocument();
  });

  it("hides layer controls when the runtime config disables layers", async () => {
    mockApi();
    render(<EditorWorkspace />);

    expect(await screen.findByText("API 已连接")).toBeInTheDocument();
    await uploadFile();
    expect(await screen.findByText("编辑预览")).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "添加全图局部调整" }),
    );

    expect(screen.queryByRole("combobox", { name: "混合模式 1" })).toBeNull();
    expect(screen.queryByRole("button", { name: "上移图层 1" })).toBeNull();
  });
});
