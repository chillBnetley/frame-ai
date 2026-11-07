import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EditorWorkspace } from "@/features/editor/editor-workspace";
import { DEFAULT_ADJUSTMENTS, normalizeRecipe } from "@/lib/recipe";
import type { EditRecipe } from "@/types/session";
import { analysisReport, ANALYSIS_ID } from "./analysis-fixtures";
import {
  critiqueApply,
  PATCH_ID,
  PLAN_ID,
  photographerCritique,
  photographerPatch,
  photographerPlan,
  styleCatalog,
  unsupportedPatch,
} from "./photographer-fixtures";
import {
  IMAGE_ID,
  NEXT_REVISION_ID,
  REVISION_ID,
  SESSION_ID,
} from "./session-fixtures";

const PLAN_RECIPE = normalizeRecipe({
  adjustments: { ...DEFAULT_ADJUSTMENTS, contrast: 12 },
});

const MONO_RECIPE = normalizeRecipe({
  adjustments: { ...DEFAULT_ADJUSTMENTS, saturation: -100, contrast: 8 },
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function sessionState(source: "initial" | "ai" = "initial") {
  const recipe = source === "ai" ? PLAN_RECIPE : normalizeRecipe({});
  const revisionId = source === "ai" ? NEXT_REVISION_ID : REVISION_ID;
  return {
    sessionId: SESSION_ID,
    imageId: IMAGE_ID,
    activeRevisionId: revisionId,
    headRevisionId: revisionId,
    canUndo: source === "ai",
    canRedo: false,
    revision: {
      id: revisionId,
      revisionNo: source === "ai" ? 2 : 1,
      parentId: source === "ai" ? REVISION_ID : null,
      source,
      recipe,
      createdAt: "2026-11-02T00:00:00Z",
    },
  };
}

function installFlowMock() {
  const calls = {
    plans: [] as Array<Record<string, unknown>>,
    chats: [] as Array<Record<string, unknown>>,
    critiques: [] as Array<Record<string, unknown>>,
    applies: [] as Array<Record<string, unknown>>,
    renders: [] as Array<Record<string, unknown>>,
    revisions: [] as Array<Record<string, unknown>>,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
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
      if (url.endsWith(`/api/v1/sessions/${SESSION_ID}`)) {
        return jsonResponse(
          sessionState(calls.revisions.length > 0 ? "ai" : "initial"),
        );
      }
      if (
        url.endsWith(`/api/v1/sessions/${SESSION_ID}/revisions`) &&
        init?.method === "POST"
      ) {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        calls.revisions.push(body);
        const accepted = sessionState("ai");
        return jsonResponse(
          {
            ...accepted,
            revision: {
              ...accepted.revision,
              recipe: normalizeRecipe(body.recipe as Partial<EditRecipe>),
            },
          },
          201,
        );
      }
      if (url.includes(`/api/v1/sessions/${SESSION_ID}/revisions`)) {
        return jsonResponse({ items: [], nextCursor: null });
      }
      if (url.endsWith(`/api/v1/sessions/${SESSION_ID}/render`)) {
        calls.renders.push(
          JSON.parse(String(init?.body)) as Record<string, unknown>,
        );
        return jsonResponse({
          previewUrl: `/api/v1/previews/flow-${calls.renders.length}`,
          width: 1600,
          height: 1200,
          quality: "final",
          cacheHit: false,
          warnings: [],
        });
      }
      if (url.endsWith("/api/v1/analysis") && init?.method === "POST") {
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
          resultAvailable: true,
          result: analysisReport(),
        });
      }
      if (url.endsWith(`/api/v1/analysis/${ANALYSIS_ID}/result`)) {
        return jsonResponse(analysisReport());
      }
      if (url.endsWith("/api/v1/ai/photographer/styles")) {
        return jsonResponse({ styles: styleCatalog() });
      }
      if (
        url.endsWith("/api/v1/ai/photographer/plan") &&
        init?.method === "POST"
      ) {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        calls.plans.push(body);
        const styleId = typeof body.styleId === "string" ? body.styleId : null;
        return jsonResponse(
          photographerPlan({
            sessionId: SESSION_ID,
            imageId: IMAGE_ID,
            analysisId: ANALYSIS_ID,
            mode: styleId === null ? "auto" : "style",
            recipe: styleId === null ? PLAN_RECIPE : MONO_RECIPE,
            styleId,
            styleVersion: styleId === null ? null : "1.0",
            styleStrength:
              typeof body.styleStrength === "number"
                ? body.styleStrength
                : null,
          }),
        );
      }
      if (
        url.endsWith("/api/v1/ai/photographer/chat") &&
        init?.method === "POST"
      ) {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        calls.chats.push(body);
        const instruction = String(body.instruction ?? "");
        const planId = String(body.planId ?? "");
        return jsonResponse(
          instruction.includes("删除")
            ? unsupportedPatch({ planId })
            : photographerPatch({ planId }),
        );
      }
      if (
        url.endsWith("/api/v1/ai/photographer/critique/apply") &&
        init?.method === "POST"
      ) {
        calls.applies.push(
          JSON.parse(String(init.body)) as Record<string, unknown>,
        );
        return jsonResponse(critiqueApply());
      }
      if (
        url.endsWith("/api/v1/ai/photographer/critique") &&
        init?.method === "POST"
      ) {
        calls.critiques.push(
          JSON.parse(String(init.body)) as Record<string, unknown>,
        );
        return jsonResponse(photographerCritique());
      }
      return jsonResponse(
        { error: { code: "not_found", message: "Not found", details: {} } },
        404,
      );
    }),
  );
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
});

describe("AI photographer flow", () => {
  it("runs analysis, plans, previews, and accepts as an ai revision", async () => {
    window.history.replaceState({}, "", `/?session=${SESSION_ID}`);
    const calls = installFlowMock();
    render(<EditorWorkspace />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /AI 自动优化/ })).toBeEnabled(),
    );
    await userEvent.click(screen.getByRole("button", { name: /AI 自动优化/ }));

    await userEvent.click(screen.getByRole("button", { name: "开始自动优化" }));

    await waitFor(() => expect(calls.plans).toHaveLength(1));
    expect(calls.plans[0]).toMatchObject({
      sessionId: SESSION_ID,
      analysisId: ANALYSIS_ID,
      mode: "auto",
    });

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "接受方案" })).toBeEnabled(),
    );
    expect(
      screen.getByText("模拟方案（未调用真实 Planner 模型）"),
    ).toBeInTheDocument();

    await waitFor(() =>
      expect(
        calls.renders.some(
          (body) =>
            (body.recipe as { adjustments?: { contrast?: number } }).adjustments
              ?.contrast === 12,
        ),
      ).toBe(true),
    );

    await userEvent.click(screen.getByRole("button", { name: "原图" }));
    expect(screen.getByTestId("photographer-original")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "AI 方案预览" }));
    expect(
      screen.queryByTestId("photographer-original"),
    ).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "接受方案" }));

    await waitFor(() => expect(calls.revisions).toHaveLength(1));
    expect(calls.revisions[0]).toMatchObject({
      source: "ai",
      parentRevisionId: REVISION_ID,
    });
    expect(
      (calls.revisions[0]?.recipe as { adjustments: { contrast: number } })
        .adjustments.contrast,
    ).toBe(12);

    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "接受方案" }),
      ).not.toBeInTheDocument(),
    );
  });

  it("re-plans on style and strength changes without accepting them", async () => {
    window.history.replaceState({}, "", `/?session=${SESSION_ID}`);
    const calls = installFlowMock();
    render(<EditorWorkspace />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /AI 自动优化/ })).toBeEnabled(),
    );
    await userEvent.click(screen.getByRole("button", { name: /AI 自动优化/ }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "黑白纪实" })).toBeEnabled(),
    );
    await userEvent.click(screen.getByRole("button", { name: "开始自动优化" }));
    await waitFor(() => expect(calls.plans).toHaveLength(1));
    expect(calls.plans[0]).toMatchObject({ mode: "auto" });

    await userEvent.click(screen.getByRole("button", { name: "黑白纪实" }));
    await waitFor(() => expect(calls.plans).toHaveLength(2));
    expect(calls.plans[1]).toMatchObject({
      mode: "style",
      styleId: "monochrome",
      styleStrength: 0.7,
    });

    const slider = screen.getByRole("slider", { name: "风格强度" });
    expect(slider).toHaveValue("0.7");
    fireEvent.change(slider, { target: { value: "0.35" } });
    expect(slider).toHaveValue("0.35");
    fireEvent.focusOut(slider);
    await waitFor(() => expect(calls.plans).toHaveLength(3));
    expect(calls.plans[2]).toMatchObject({
      mode: "style",
      styleId: "monochrome",
      styleStrength: 0.35,
    });

    expect(
      screen.getByText(/风格由参数组合实时计算，不依赖 LUT/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "接受方案" })).toBeEnabled();
    expect(calls.revisions).toHaveLength(0);

    await userEvent.click(screen.getByRole("button", { name: "放弃" }));
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "接受方案" }),
      ).not.toBeInTheDocument(),
    );
    expect(calls.revisions).toHaveLength(0);
  });
});

describe("AI photographer chat flow", () => {
  async function openPanelWithPlan(calls: ReturnType<typeof installFlowMock>) {
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /AI 自动优化/ })).toBeEnabled(),
    );
    await userEvent.click(screen.getByRole("button", { name: /AI 自动优化/ }));
    await userEvent.click(screen.getByRole("button", { name: "开始自动优化" }));
    await waitFor(() => expect(calls.plans).toHaveLength(1));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "接受方案" })).toBeEnabled(),
    );
  }

  it("sends an instruction, previews the patch, and accepts it as an ai revision", async () => {
    window.history.replaceState({}, "", `/?session=${SESSION_ID}`);
    const calls = installFlowMock();
    render(<EditorWorkspace />);
    await openPanelWithPlan(calls);

    await userEvent.type(
      screen.getByRole("textbox", { name: "调整指令" }),
      "降低饱和度",
    );
    await userEvent.click(screen.getByRole("button", { name: "应用这条指令" }));

    await waitFor(() => expect(calls.chats).toHaveLength(1));
    expect(calls.chats[0]).toMatchObject({
      planId: PLAN_ID,
      instruction: "降低饱和度",
    });
    expect(
      screen.getByRole("heading", { name: "对话调整建议" }),
    ).toBeInTheDocument();
    expect(screen.getByText("1 项参数变化")).toBeInTheDocument();
    expect(
      within(screen.getByRole("region", { name: "参数变化" })).getByText(
        "饱和度",
      ),
    ).toBeInTheDocument();

    await waitFor(() =>
      expect(
        calls.renders.some(
          (body) =>
            (body.recipe as { adjustments?: { saturation?: number } })
              .adjustments?.saturation === -8,
        ),
      ).toBe(true),
    );
    expect(calls.revisions).toHaveLength(0);

    await userEvent.type(
      screen.getByRole("textbox", { name: "调整指令" }),
      "再提高一点对比",
    );
    await userEvent.click(screen.getByRole("button", { name: "应用这条指令" }));
    await waitFor(() => expect(calls.chats).toHaveLength(2));
    expect(calls.chats[1]).toMatchObject({
      planId: PATCH_ID,
      instruction: "再提高一点对比",
    });

    await userEvent.click(screen.getByRole("button", { name: "接受方案" }));

    await waitFor(() => expect(calls.revisions).toHaveLength(1));
    expect(calls.revisions[0]).toMatchObject({
      source: "ai",
      parentRevisionId: REVISION_ID,
    });
    expect(
      (calls.revisions[0]?.recipe as { adjustments: { saturation: number } })
        .adjustments.saturation,
    ).toBe(-8);

    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "接受方案" }),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.queryByRole("heading", { name: "对话调整建议" }),
    ).not.toBeInTheDocument();
  });

  it("keeps an unsupported instruction at the capability boundary", async () => {
    window.history.replaceState({}, "", `/?session=${SESSION_ID}`);
    const calls = installFlowMock();
    render(<EditorWorkspace />);
    await openPanelWithPlan(calls);

    await userEvent.click(
      screen.getByRole("button", { name: "删除背景里的人物" }),
    );

    await waitFor(() => expect(calls.chats).toHaveLength(1));
    expect(
      screen.getByRole("heading", { name: "这项调整不支持" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("当前配方未发生变化，画面保持你已有的调整。"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("这条指令没有产生参数变化，接受按钮已停用。"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "接受方案" })).toBeDisabled();
    expect(calls.revisions).toHaveLength(0);

    await userEvent.click(screen.getByRole("button", { name: "放弃" }));
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "这项调整不支持" }),
      ).not.toBeInTheDocument(),
    );
    expect(calls.revisions).toHaveLength(0);
  });

  it("re-anchors on a fresh plan after the user discards a patch", async () => {
    window.history.replaceState({}, "", `/?session=${SESSION_ID}`);
    const calls = installFlowMock();
    render(<EditorWorkspace />);
    await openPanelWithPlan(calls);

    await userEvent.type(
      screen.getByRole("textbox", { name: "调整指令" }),
      "降低饱和度",
    );
    await userEvent.click(screen.getByRole("button", { name: "应用这条指令" }));
    await waitFor(() => expect(calls.chats).toHaveLength(1));

    await userEvent.click(screen.getByRole("button", { name: "放弃" }));
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "对话调整建议" }),
      ).not.toBeInTheDocument(),
    );

    await userEvent.type(
      screen.getByRole("textbox", { name: "调整指令" }),
      "再提高一点对比",
    );
    await userEvent.click(screen.getByRole("button", { name: "应用这条指令" }));

    await waitFor(() => expect(calls.chats).toHaveLength(2));
    expect(calls.plans).toHaveLength(2);
    expect(calls.chats[1]).toMatchObject({
      planId: PLAN_ID,
      instruction: "再提高一点对比",
    });
    expect(calls.revisions).toHaveLength(0);
  });
});

describe("AI photographer critique flow", () => {
  async function openPanelWithCritique(
    calls: ReturnType<typeof installFlowMock>,
  ) {
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /AI 自动优化/ })).toBeEnabled(),
    );
    await userEvent.click(screen.getByRole("button", { name: /AI 自动优化/ }));
    await userEvent.click(screen.getByRole("button", { name: "开始自动优化" }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "生成摄影点评" }),
      ).toBeEnabled(),
    );

    await userEvent.click(screen.getByRole("button", { name: "生成摄影点评" }));
    await waitFor(() => expect(calls.critiques).toHaveLength(1));
    await screen.findByRole("region", { name: "后期建议" });
  }

  it("cites the report behind every conclusion", async () => {
    window.history.replaceState({}, "", `/?session=${SESSION_ID}`);
    const calls = installFlowMock();
    render(<EditorWorkspace />);
    await openPanelWithCritique(calls);

    expect(calls.critiques[0]).toEqual({ analysisId: ANALYSIS_ID });
    const critique = screen.getByRole("region", { name: "AI 摄影点评" });
    expect(within(critique).getByText("规则生成")).toBeInTheDocument();
    expect(
      within(critique).getByText(
        "本次点评基于模拟分析结果（未调用真实视觉模型）",
      ),
    ).toBeInTheDocument();
    for (const title of ["优点", "技术观测", "可能的问题", "创作解读"]) {
      expect(within(critique).getByRole("region", { name: title })).toBeInTheDocument();
    }
    expect(within(critique).getAllByText(/^证据 \d+ 项$/).length).toBeGreaterThan(0);
  });

  it("previews a suggestion and accepts it as an ai revision", async () => {
    window.history.replaceState({}, "", `/?session=${SESSION_ID}`);
    const calls = installFlowMock();
    render(<EditorWorkspace />);
    // The plan lands first, so the critique preview visibly replaces it.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /AI 自动优化/ })).toBeEnabled(),
    );
    await userEvent.click(screen.getByRole("button", { name: /AI 自动优化/ }));
    await userEvent.click(screen.getByRole("button", { name: "开始自动优化" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "接受方案" })).toBeEnabled(),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "生成摄影点评" }),
      ).toBeEnabled(),
    );
    await userEvent.click(screen.getByRole("button", { name: "生成摄影点评" }));
    await screen.findByRole("region", { name: "后期建议" });

    const suggestions = screen.getByRole("region", { name: "后期建议" });
    await userEvent.click(
      within(suggestions).getByText("轻微压低高光以保留天空层次。"),
    );
    expect(calls.applies).toHaveLength(0);

    await userEvent.click(within(suggestions).getByText("应用到编辑"));
    await waitFor(() => expect(calls.applies).toHaveLength(1));
    expect(calls.applies[0]).toMatchObject({
      sessionId: SESSION_ID,
      patch: { highlights: -20, whites: -8 },
    });

    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "点评建议预览" }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("2 项参数变化")).toBeInTheDocument();
    expect(screen.queryByText("自然平衡")).not.toBeInTheDocument();
    expect(calls.revisions).toHaveLength(0);

    await waitFor(() =>
      expect(
        calls.renders.some(
          (body) =>
            (body.recipe as { adjustments?: { highlights?: number } }).adjustments
              ?.highlights === -20,
        ),
      ).toBe(true),
    );

    await userEvent.click(screen.getByRole("button", { name: "接受方案" }));
    await waitFor(() => expect(calls.revisions).toHaveLength(1));
    expect(calls.revisions[0]).toMatchObject({
      source: "ai",
      parentRevisionId: REVISION_ID,
    });
    const accepted = calls.revisions[0]?.recipe as {
      adjustments: { highlights: number; whites: number };
    };
    expect(accepted.adjustments.highlights).toBe(-20);
    expect(accepted.adjustments.whites).toBe(-8);

    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "接受方案" }),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.queryByRole("heading", { name: "点评建议预览" }),
    ).not.toBeInTheDocument();
  });

  it("leaves composition advice as advice when no parameter can express it", async () => {
    window.history.replaceState({}, "", `/?session=${SESSION_ID}`);
    const calls = installFlowMock();
    render(<EditorWorkspace />);
    await openPanelWithCritique(calls);

    const suggestions = screen.getByRole("region", { name: "后期建议" });
    expect(
      within(suggestions).getByText(
        "这条建议不涉及可调参数，需要通过裁切或拍摄时机实现。",
      ),
    ).toBeInTheDocument();
    expect(within(suggestions).getAllByText("应用到编辑")).toHaveLength(1);

    await userEvent.click(screen.getByRole("button", { name: "收起点评" }));
    await waitFor(() =>
      expect(
        within(screen.getByRole("region", { name: "AI 摄影点评" })).getByRole(
          "button",
          { name: "生成摄影点评" },
        ),
      ).toBeEnabled(),
    );
    expect(calls.applies).toHaveLength(0);
    expect(calls.revisions).toHaveLength(0);
  });
});
