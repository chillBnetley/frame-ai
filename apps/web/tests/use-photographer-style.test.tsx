import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { UseAnalysisResult } from "@/features/analysis/hooks/use-analysis";
import { EditorProvider } from "@/features/editor/state/editor-context";
import { usePhotographer } from "@/features/photographer/hooks/use-photographer";
import { analysisReport, ANALYSIS_ID } from "./analysis-fixtures";
import { photographerPlan, styleCatalog } from "./photographer-fixtures";
import { IMAGE_ID, readyEditorState, SESSION_ID } from "./session-fixtures";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function analysisState(
  overrides: Partial<UseAnalysisResult> = {},
): UseAnalysisResult {
  return {
    analysisId: ANALYSIS_ID,
    status: "completed",
    stage: "completed",
    isMock: true,
    report: analysisReport(),
    error: null,
    requestPending: false,
    running: false,
    start: vi.fn(),
    retry: vi.fn(),
    rerun: vi.fn(),
    ...overrides,
  };
}

function wrapper({ children }: { children: ReactNode }) {
  return <EditorProvider initialState={readyEditorState()}>{children}</EditorProvider>;
}

interface PlanCalls {
  plans: Array<Record<string, unknown>>;
  revisionPosts: number;
  releaseFirst: () => void;
}

/**
 * `gateFirst` holds the first plan response open so a test can change the style
 * while a request is genuinely in flight.
 */
function installPlanMock(gateFirst = false): PlanCalls {
  const calls: PlanCalls = {
    plans: [],
    revisionPosts: 0,
    releaseFirst: () => {},
  };
  let open = !gateFirst;
  const gate = new Promise<void>((resolve) => {
    calls.releaseFirst = () => {
      open = true;
      resolve();
    };
  });

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/v1/ai/photographer/plan") && init?.method === "POST") {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        calls.plans.push(body);
        if (!open) {
          await gate;
        }
        const styleId = typeof body.styleId === "string" ? body.styleId : null;
        return jsonResponse(
          photographerPlan({
            sessionId: SESSION_ID,
            imageId: IMAGE_ID,
            analysisId: ANALYSIS_ID,
            mode: body.mode === "style" ? "style" : "auto",
            styleId,
            styleVersion: styleId === null ? null : "1.0",
            styleStrength:
              typeof body.styleStrength === "number" ? body.styleStrength : null,
          }),
        );
      }
      if (url.endsWith(`/api/v1/sessions/${SESSION_ID}/revisions`)) {
        calls.revisionPosts += 1;
      }
      return jsonResponse(
        { error: { code: "not_found", message: "Not found", details: {} } },
        404,
      );
    }),
  );
  return calls;
}

function renderPhotographer() {
  return renderHook(() => usePhotographer(analysisState()), { wrapper });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("usePhotographer style selection", () => {
  it("re-generates the plan in style mode without accepting it", async () => {
    const calls = installPlanMock();
    const { result } = renderPhotographer();

    act(() => {
      result.current.start();
    });
    await waitFor(() => expect(result.current.proposal.status).toBe("ready"));
    expect(calls.plans[0]).toMatchObject({ mode: "auto" });
    expect(calls.plans[0]).not.toHaveProperty("styleId");

    const monochrome = styleCatalog().find((style) => style.id === "monochrome");
    expect(monochrome).toBeDefined();
    await act(async () => {
      result.current.selectStyle(monochrome ?? null);
    });

    await waitFor(() => expect(calls.plans).toHaveLength(2));
    expect(calls.plans[1]).toMatchObject({
      sessionId: SESSION_ID,
      analysisId: ANALYSIS_ID,
      mode: "style",
      styleId: "monochrome",
      styleStrength: 0.7,
    });
    await waitFor(() => expect(result.current.proposal.status).toBe("ready"));
    expect(result.current.proposal.plan?.styleId).toBe("monochrome");
    expect(result.current.proposal.plan?.mode).toBe("style");
    expect(calls.revisionPosts).toBe(0);
    expect(result.current.canAccept).toBe(true);
  });

  it("waits for the strength commit before re-planning", async () => {
    const calls = installPlanMock();
    const { result } = renderPhotographer();

    act(() => {
      result.current.start();
    });
    await waitFor(() => expect(calls.plans).toHaveLength(1));
    const portrait = styleCatalog()[0];
    await act(async () => {
      result.current.selectStyle(portrait);
    });
    await waitFor(() => expect(calls.plans).toHaveLength(2));

    act(() => {
      result.current.setStyleStrength(0.25);
    });
    await act(async () => {});
    expect(result.current.styleStrength).toBe(0.25);
    expect(calls.plans).toHaveLength(2);

    act(() => {
      result.current.commitStyleStrength();
    });
    await waitFor(() => expect(calls.plans).toHaveLength(3));
    expect(calls.plans[2]).toMatchObject({
      mode: "style",
      styleId: "portrait",
      styleStrength: 0.25,
    });
  });

  it("sends no style fields when the selection returns to auto", async () => {
    const calls = installPlanMock();
    const { result } = renderPhotographer();

    act(() => {
      result.current.start();
    });
    await waitFor(() => expect(calls.plans).toHaveLength(1));
    await act(async () => {
      result.current.selectStyle(styleCatalog()[4]);
    });
    await waitFor(() => expect(calls.plans).toHaveLength(2));

    await act(async () => {
      result.current.selectStyle(null);
    });

    await waitFor(() => expect(calls.plans).toHaveLength(3));
    expect(calls.plans[2]).toMatchObject({ mode: "auto" });
    expect(calls.plans[2]).not.toHaveProperty("styleId");
    expect(calls.plans[2]).not.toHaveProperty("styleStrength");
  });

  it("keeps an idle picker quiet until the user asks for a plan", async () => {
    const calls = installPlanMock();
    const { result } = renderPhotographer();

    await act(async () => {
      result.current.selectStyle(styleCatalog()[2]);
    });
    expect(calls.plans).toHaveLength(0);

    act(() => {
      result.current.start();
    });
    await waitFor(() => expect(calls.plans).toHaveLength(1));
    expect(calls.plans[0]).toMatchObject({
      mode: "style",
      styleId: "landscape",
      styleStrength: 0.55,
    });
  });

  it("waits for an in-flight proposal before re-planning a style change", async () => {
    const calls = installPlanMock(true);
    const { result } = renderPhotographer();

    act(() => {
      result.current.start();
    });
    expect(result.current.proposal.status).toBe("loading");
    await act(async () => {
      result.current.selectStyle(styleCatalog()[5]);
    });
    expect(calls.plans).toHaveLength(1);

    calls.releaseFirst();
    await waitFor(() => expect(calls.plans).toHaveLength(2));
    expect(calls.plans[0]).toMatchObject({ mode: "auto" });
    expect(calls.plans[1]).toMatchObject({
      mode: "style",
      styleId: "cinematic",
      styleStrength: 0.65,
    });
  });
});
