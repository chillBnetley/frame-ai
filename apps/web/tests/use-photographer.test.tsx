import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { UseAnalysisResult } from "@/features/analysis/hooks/use-analysis";
import { EditorProvider } from "@/features/editor/state/editor-context";
import { usePhotographer } from "@/features/photographer/hooks/use-photographer";
import { analysisReport } from "./analysis-fixtures";
import { photographerPlan } from "./photographer-fixtures";
import { readyEditorState } from "./session-fixtures";

function analysisState(
  overrides: Partial<UseAnalysisResult> = {},
): UseAnalysisResult {
  return {
    analysisId: null,
    status: null,
    stage: null,
    isMock: false,
    report: null,
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

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("usePhotographer analysis handoff", () => {
  it("waits for the report when a deduplicated analysis reports completed first", async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify(photographerPlan()), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { result, rerender } = renderHook(
      ({ analysis }: { analysis: UseAnalysisResult }) => usePhotographer(analysis),
      { wrapper, initialProps: { analysis: analysisState() } },
    );

    act(() => {
      result.current.start();
    });

    const completedWithoutReport = analysisState({
      status: "completed",
      stage: "completed",
    });
    rerender({ analysis: completedWithoutReport });
    await act(async () => {});

    expect(result.current.proposal.status).not.toBe("error");
    expect(fetchMock).not.toHaveBeenCalled();

    rerender({
      analysis: analysisState({
        status: "completed",
        stage: "completed",
        analysisId: analysisReport().analysisId,
        report: analysisReport(),
      }),
    });

    await waitFor(() => {
      expect(result.current.proposal.status).toBe("ready");
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
