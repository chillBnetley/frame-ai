import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EditorWorkspace } from "@/features/editor/editor-workspace";

const HEALTH = {
  status: "ok",
  service: "FRAME AI API",
  version: "0.1.0",
  storage: { ok: true, writable: true },
};

const CONFIG = {
  maxUploadBytes: 20 * 1024 * 1024,
  maxImagePixels: 40_000_000,
  allowedMimeTypes: ["image/jpeg", "image/png", "image/webp"],
  features: {
    layers: false,
    semanticMasks: {
      enabled: false,
      person: false,
      sky: false,
    },
    semanticMaskModels: { person: null, sky: null },
  },
};

const IMAGE_ID = "2b1d0f76-4a1e-4de0-8a7b-3c0f2f9c1a55";
const SESSION_ID = "9d7c2a11-5b62-4f8e-9a41-0f3c7e6b2d18";
const REVISION_ID = "6c0f4a92-3d15-4c8b-8f27-1a9e5b6d0c34";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function sessionState() {
  return {
    sessionId: SESSION_ID,
    imageId: IMAGE_ID,
    activeRevisionId: REVISION_ID,
    headRevisionId: REVISION_ID,
    canUndo: false,
    canRedo: false,
    revision: {
      id: REVISION_ID,
      revisionNo: 1,
      parentId: null,
      source: "initial",
      recipe: { schemaVersion: "2.0", styleId: "natural", styleStrength: 0 },
      createdAt: "2026-11-04T00:00:00Z",
    },
  };
}

function mockHealthyApi() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      const method = init?.method ?? "GET";
      if (url.endsWith("/api/v1/health")) {
        return jsonResponse(HEALTH);
      }
      if (url.endsWith("/api/v1/config")) {
        return jsonResponse(CONFIG);
      }
      if (url.endsWith("/api/v1/images") && method === "POST") {
        return jsonResponse(
          {
            imageId: IMAGE_ID,
            originalName: "street.png",
            width: 800,
            height: 600,
            exifOrientation: 1,
            mimeType: "image/png",
            bytes: 2048,
          },
          201,
        );
      }
      if (url.endsWith("/api/v1/sessions") && method === "POST") {
        return jsonResponse(sessionState(), 201);
      }
      if (url.includes(`/api/v1/sessions/${SESSION_ID}/revisions`)) {
        return method === "POST"
          ? jsonResponse(
              {
                ...sessionState(),
                revision: {
                  ...sessionState().revision,
                  id: REVISION_ID,
                  revisionNo: 2,
                  source: "user",
                },
              },
              201,
            )
          : jsonResponse({ items: [], nextCursor: null });
      }
      if (url.endsWith(`/api/v1/sessions/${SESSION_ID}/render`)) {
        return jsonResponse({
          previewUrl: "/api/v1/previews/mocked-preview",
          width: 800,
          height: 600,
          quality: "final",
          cacheHit: false,
        });
      }
      return jsonResponse({ error: { code: "not_found", message: "Not found", details: {} } }, 404);
    }),
  );
}

async function openEditor(): Promise<HTMLElement> {
  const { container } = render(<EditorWorkspace />);
  const file = new File([new Uint8Array([1, 2, 3, 4])], "street.png", { type: "image/png" });
  await userEvent.upload(screen.getByTestId("file-input"), file);
  await screen.findByText("编辑预览", undefined, { timeout: 5000 });
  await screen.findByRole("heading", { name: "曲线" });
  await screen.findByText("HSL 色彩");
  await screen.findByText("颜色分级");
  await screen.findByText("局部调整");
  return container;
}

async function severeViolations(container: HTMLElement) {
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  return results.violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical",
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("EditorWorkspace accessibility", () => {
  it("supports keyboard activation of the upload picker", async () => {
    mockHealthyApi();
    render(<EditorWorkspace />);

    await screen.findByText("API 已连接");
    const picker = screen.getByRole("button", { name: /拖入一张照片/ });
    const input = screen.getByTestId("file-input") as HTMLInputElement;
    const clickSpy = vi.spyOn(input, "click").mockImplementation(() => {});

    picker.focus();
    expect(picker).toHaveFocus();
    await userEvent.keyboard("{Enter}");

    expect(clickSpy).toHaveBeenCalledTimes(1);
  });

  it("has no serious or critical axe violations", async () => {
    mockHealthyApi();
    const { container } = render(<EditorWorkspace />);

    await screen.findByText("API 已连接");
    expect(await severeViolations(container)).toEqual([]);
  });

  it("has no serious or critical violations with all stage-4 panels open", async () => {
    mockHealthyApi();
    const container = await openEditor();

    await waitFor(() => {
      expect(screen.getByTestId("curve-svg")).toBeInTheDocument();
    });

    expect(await severeViolations(container)).toEqual([]);
  });
});
