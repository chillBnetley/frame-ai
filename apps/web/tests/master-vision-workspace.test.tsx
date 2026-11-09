import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MasterVisionWorkspace } from "@/features/master-vision/components/workspace/master-vision-workspace";

import { ANALYSIS_ID, analysisReport } from "./analysis-fixtures";
import {
  GENRE_ITEM,
  MASTER_STYLE_ID,
  conversionModeList,
  masterVisionPlan,
  styleDetail,
  styleFit,
  styleItem,
} from "./master-vision-fixtures";
import { IMAGE_ID, NEXT_REVISION_ID, SESSION_ID, sessionState } from "./session-fixtures";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function installWorkspaceMock() {
  const calls: Array<{ method: string; url: string; body: unknown }> = [];
  let renders = 0;
  const plan = masterVisionPlan();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body =
        typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : init?.body;
      calls.push({ method, url, body });

      if (url.endsWith("/api/v1/styles")) {
        return jsonResponse({ styles: [styleItem(), GENRE_ITEM] });
      }
      if (url.endsWith("/api/v1/ai/photographer/conversion-modes")) {
        return jsonResponse(conversionModeList());
      }
      if (url.endsWith(`/api/v1/styles/${MASTER_STYLE_ID}`)) {
        return jsonResponse(styleDetail());
      }
      if (url.includes(`/api/v1/styles/${MASTER_STYLE_ID}/fit`)) {
        return jsonResponse(styleFit());
      }
      if (url.endsWith("/api/v1/images") && method === "POST") {
        return jsonResponse({
          imageId: IMAGE_ID,
          originalName: "photo.png",
          width: 1600,
          height: 1200,
          exifOrientation: 1,
          mimeType: "image/png",
          bytes: 3,
        });
      }
      if (url.endsWith("/api/v1/sessions") && method === "POST") {
        return jsonResponse(sessionState(), 201);
      }
      if (url.endsWith("/api/v1/analysis") && method === "POST") {
        return jsonResponse(
          {
            analysisId: ANALYSIS_ID,
            status: "completed",
            stage: "completed",
            deduplicated: false,
          },
          202,
        );
      }
      if (url.endsWith(`/api/v1/analysis/${ANALYSIS_ID}`)) {
        return jsonResponse({
          analysisId: ANALYSIS_ID,
          status: "completed",
          stage: "completed",
          isMock: true,
          resultAvailable: true,
          result: analysisReport(),
          createdAt: "2026-11-08T00:00:00Z",
          updatedAt: "2026-11-08T00:00:01Z",
        });
      }
      if (url.endsWith(`/api/v1/sessions/${SESSION_ID}/render`)) {
        renders += 1;
        return jsonResponse({
          previewUrl: `/preview-${renders}.jpg`,
          width: 1600,
          height: 1200,
          quality: "draft",
          cacheHit: false,
          warnings: [],
        });
      }
      if (url.endsWith("/api/v1/ai/photographer/plan") && method === "POST") {
        return jsonResponse(plan);
      }
      if (url.endsWith(`/api/v1/sessions/${SESSION_ID}/revisions`) && method === "POST") {
        return jsonResponse(
          sessionState({
            recipe: plan.recipe,
            revisionId: NEXT_REVISION_ID,
            headRevisionId: NEXT_REVISION_ID,
            revisionNo: 2,
            source: "ai",
            canUndo: true,
          }),
          201,
        );
      }
      return jsonResponse(
        { error: { code: "not_found", message: `missing ${url}`, details: {} } },
        404,
      );
    }),
  );
  return calls;
}

async function uploadPhoto(user: ReturnType<typeof userEvent.setup>) {
  const input = screen.getByTestId("file-input") as HTMLInputElement;
  await user.upload(input, new File([new Uint8Array([1, 2, 3])], "photo.png", { type: "image/png" }));
}

describe("MasterVisionWorkspace", () => {
  it("runs upload, analysis, fit, plan, render, and AI save end to end", async () => {
    const calls = installWorkspaceMock();
    const user = userEvent.setup();
    render(<MasterVisionWorkspace initialStyleId={MASTER_STYLE_ID} />);

    expect(await screen.findByRole("heading", { name: "风格创作工作台" })).toBeInTheDocument();
    await uploadPhoto(user);

    const generate = await screen.findByRole("button", { name: /生成风格方案/ });
    await waitFor(() => expect(generate).toBeEnabled());
    expect(await screen.findByText("街道场景与强光影结构为风格提供了良好的基础。")).toBeInTheDocument();

    await user.click(generate);
    const save = await screen.findByRole("button", { name: /应用并保存/ });
    await waitFor(() => expect(save).toBeEnabled());
    expect(await screen.findByAltText("风格处理结果")).toBeInTheDocument();
    expect(screen.getAllByText(/将画面转为中性黑白影调/).length).toBeGreaterThan(0);

    fireEvent.change(screen.getByRole("slider", { name: "风格强度" }), {
      target: { value: "85" },
    });
    expect(screen.getByText(/模式或强度已改变/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /应用并保存/ })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: /重新生成/ }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /应用并保存/ })).toBeEnabled(),
    );

    await user.click(screen.getByRole("button", { name: /应用并保存/ }));
    expect(await screen.findByRole("button", { name: "已保存为 AI 创作" })).toBeDisabled();

    const planCall = calls.find((call) => call.url.endsWith("/ai/photographer/plan"));
    expect(planCall?.body).toMatchObject({
      sessionId: SESSION_ID,
      analysisId: ANALYSIS_ID,
      mode: "style",
      styleId: MASTER_STYLE_ID,
      styleStrength: 0.6,
      conversionMode: "style",
    });
    const revision = calls.find(
      (call) => call.method === "POST" && call.url.endsWith(`/sessions/${SESSION_ID}/revisions`),
    );
    expect(revision?.body).toMatchObject({ source: "ai" });
  });

  it("reports an upload failure without leaving the empty state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/api/v1/styles")) {
          return jsonResponse({ styles: [styleItem()] });
        }
        if (url.endsWith("/api/v1/ai/photographer/conversion-modes")) {
          return jsonResponse(conversionModeList());
        }
        if (url.includes("/api/v1/styles/")) {
          return jsonResponse(styleDetail());
        }
        throw new Error("offline");
      }),
    );
    const user = userEvent.setup();
    render(<MasterVisionWorkspace initialStyleId={MASTER_STYLE_ID} />);
    await screen.findByRole("heading", { name: "风格创作工作台" });

    await uploadPhoto(user);

    expect(await screen.findByText(/无法连接/)).toBeInTheDocument();
    expect(screen.getByText("尚未选择照片")).toBeInTheDocument();
  });
});
