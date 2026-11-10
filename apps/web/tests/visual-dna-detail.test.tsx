import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VisualDnaDetail } from "@/features/visual-dna/components/visual-dna-detail";

import {
  PERSONAL_REFERENCE_ID,
  PERSONAL_STYLE_ID,
  personalStyleAnalysis,
  personalStyleAnalysisCompleted,
  personalStyleDetail,
  personalStyleFusion,
  photoVisualFeatures,
} from "./personal-style-fixtures";

const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => `/visual-dna/${PERSONAL_STYLE_ID}`,
}));

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

beforeEach(() => {
  router.push.mockReset();
});

function installDetailMock() {
  const calls: Array<{ method: string; url: string; body: unknown }> = [];
  let analysis = personalStyleAnalysis();
  let fused = false;
  let removed = false;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body =
        typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : init?.body;
      calls.push({ method, url, body });
      if (url.endsWith(`/api/v1/personal-styles/${PERSONAL_STYLE_ID}`) && method === "GET") {
        const detail = personalStyleDetail({
          references: removed ? [] : personalStyleDetail().references,
          favorite: false,
        });
        if (fused) {
          detail.style = { ...detail.style, version: "1.2" };
        }
        return jsonResponse(detail);
      }
      if (url.endsWith(`/api/v1/personal-styles/${PERSONAL_STYLE_ID}/analysis`)) {
        return jsonResponse(analysis);
      }
      if (
        url.endsWith(`/api/v1/personal-styles/${PERSONAL_STYLE_ID}/analyze`) &&
        method === "POST"
      ) {
        analysis = personalStyleAnalysisCompleted();
        return jsonResponse(analysis, 202);
      }
      if (
        url.endsWith(`/api/v1/personal-styles/${PERSONAL_STYLE_ID}/fuse`) &&
        method === "POST"
      ) {
        fused = true;
        return jsonResponse(personalStyleFusion());
      }
      if (url.endsWith(`/references/${PERSONAL_REFERENCE_ID}/features`)) {
        return jsonResponse(photoVisualFeatures());
      }
      if (
        url.endsWith(`/references/${PERSONAL_REFERENCE_ID}`) &&
        method === "DELETE"
      ) {
        removed = true;
        return jsonResponse(undefined, 204);
      }
      if (url.endsWith("/favorite") && method === "POST") {
        return jsonResponse({ styleId: PERSONAL_STYLE_ID, favorite: true });
      }
      return jsonResponse(
        { error: { code: "not_found", message: "missing", details: {} } },
        404,
      );
    }),
  );
  return calls;
}

describe("VisualDnaDetail", () => {
  it("runs analysis, shows per-photo features, and fuses a new version", async () => {
    const calls = installDetailMock();
    const user = userEvent.setup();
    render(<VisualDnaDetail styleId={PERSONAL_STYLE_ID} />);

    expect(
      await screen.findByRole("heading", { name: "克制的城市叙事" }),
    ).toBeInTheDocument();
    expect(screen.getByText("待分析")).toBeInTheDocument();
    const fuse = screen.getByRole("button", { name: "生成个人风格" });
    expect(fuse).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "开始分析" }));
    await waitFor(() =>
      expect(
        calls.some(
          (call) =>
            call.method === "POST" &&
            call.url.endsWith(`/api/v1/personal-styles/${PERSONAL_STYLE_ID}/analyze`),
        ),
      ).toBe(true),
    );
    expect(await screen.findByText("已完成")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "生成个人风格" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "查看特征" }));
    expect(
      await screen.findByText("色温偏色 -12.0（偏冷）。"),
    ).toBeInTheDocument();
    expect(screen.getByText("客观测量")).toBeInTheDocument();
    expect(screen.getByText("派生判断")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "生成个人风格" }));
    expect(await screen.findByText("本次融合结果")).toBeInTheDocument();
    expect(screen.getByText(/已生成新版本 v1.1/)).toBeInTheDocument();
  });

  it("re-analyses a single reference photo", async () => {
    const calls = installDetailMock();
    const user = userEvent.setup();
    render(<VisualDnaDetail styleId={PERSONAL_STYLE_ID} />);

    await screen.findByRole("heading", { name: "克制的城市叙事" });
    await user.click(screen.getByRole("button", { name: "重新分析" }));

    await waitFor(() =>
      expect(
        calls.some(
          (call) =>
            call.method === "POST" &&
            call.url.endsWith("/analyze") &&
            JSON.stringify(call.body).includes(PERSONAL_REFERENCE_ID),
        ),
      ).toBe(true),
    );
  });

  it("revokes reference consent after confirmation", async () => {
    const calls = installDetailMock();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    render(<VisualDnaDetail styleId={PERSONAL_STYLE_ID} />);

    await screen.findByRole("heading", { name: "克制的城市叙事" });
    expect(
      screen.getByText(/授权范围：仅用于本风格分析/),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "撤回授权" }));

    await waitFor(() =>
      expect(
        calls.some(
          (call) =>
            call.method === "DELETE" &&
            call.url.includes(`/references/${PERSONAL_REFERENCE_ID}`),
        ),
      ).toBe(true),
    );
  });

  it("toggles favorite on the detail header", async () => {
    const calls = installDetailMock();
    const user = userEvent.setup();
    render(<VisualDnaDetail styleId={PERSONAL_STYLE_ID} />);

    await screen.findByRole("heading", { name: "克制的城市叙事" });
    await user.click(screen.getByRole("button", { name: "收藏" }));

    await waitFor(() =>
      expect(
        calls.some((call) => call.method === "POST" && call.url.endsWith("/favorite")),
      ).toBe(true),
    );
    expect(await screen.findByRole("button", { name: "已收藏" })).toBeInTheDocument();
  });
});
