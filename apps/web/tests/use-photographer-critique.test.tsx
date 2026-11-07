import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { UseAnalysisResult } from "@/features/analysis/hooks/use-analysis";
import {
  EditorProvider,
  useEditorState,
} from "@/features/editor/state/editor-context";
import {
  createInitialEditorState,
  selectCanAcceptProposal,
  selectProposalAnchorId,
  type EditorState,
} from "@/features/editor/state/editor-reducer";
import {
  isActionableSuggestion,
  usePhotographerCritique,
} from "@/features/photographer/hooks/use-photographer-critique";
import type {
  CritiqueApplyResponse,
  PhotographerCritique,
  PhotographerCritiqueSuggestion,
} from "@/types/photographer";
import { ANALYSIS_ID, analysisReport } from "./analysis-fixtures";
import {
  critiqueApply,
  PATCH_ID,
  photographerCritique,
} from "./photographer-fixtures";
import { readyEditorState, SESSION_ID } from "./session-fixtures";

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

interface CritiqueCalls {
  critiques: Array<Record<string, unknown>>;
  applies: Array<Record<string, unknown>>;
  releaseCritique: () => void;
}

interface CritiqueMockOptions {
  gateCritique?: boolean;
  critique?: PhotographerCritique;
  applied?: CritiqueApplyResponse;
}

/** `gateCritique` holds the response open so a test can act mid-flight. */
function installCritiqueMock(options: CritiqueMockOptions = {}): CritiqueCalls {
  const calls: CritiqueCalls = {
    critiques: [],
    applies: [],
    releaseCritique: () => {},
  };
  let open = !options.gateCritique;
  const gate = new Promise<void>((resolve) => {
    calls.releaseCritique = () => {
      open = true;
      resolve();
    };
  });

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (
        url.endsWith("/api/v1/ai/photographer/critique/apply") &&
        init?.method === "POST"
      ) {
        calls.applies.push(
          JSON.parse(String(init.body)) as Record<string, unknown>,
        );
        return jsonResponse(options.applied ?? critiqueApply());
      }
      if (
        url.endsWith("/api/v1/ai/photographer/critique") &&
        init?.method === "POST"
      ) {
        calls.critiques.push(
          JSON.parse(String(init.body)) as Record<string, unknown>,
        );
        if (!open) {
          await gate;
        }
        return jsonResponse(options.critique ?? photographerCritique());
      }
      return jsonResponse(
        { error: { code: "not_found", message: "Not found", details: {} } },
        404,
      );
    }),
  );
  return calls;
}

function actionableSuggestion(): PhotographerCritiqueSuggestion {
  return photographerCritique().suggestions[0];
}

function withState(state: EditorState) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <EditorProvider initialState={state}>{children}</EditorProvider>;
  };
}

function renderCritique(
  state: EditorState = readyEditorState(),
  analysis: UseAnalysisResult = analysisState(),
) {
  return renderHook(
    (props: { analysis: UseAnalysisResult }) => ({
      critiqueHook: usePhotographerCritique(props.analysis),
      editor: useEditorState(),
    }),
    {
      wrapper: withState(state),
      initialProps: { analysis },
    },
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("usePhotographerCritique", () => {
  it("requests the critique for the current analysis", async () => {
    const calls = installCritiqueMock();
    const { result } = renderCritique();

    let loaded = false;
    await act(async () => {
      loaded = await result.current.critiqueHook.request();
    });

    expect(loaded).toBe(true);
    expect(calls.critiques).toEqual([{ analysisId: ANALYSIS_ID }]);
    expect(result.current.critiqueHook.critique?.analysisId).toBe(ANALYSIS_ID);
    expect(result.current.critiqueHook.pending).toBe(false);
    expect(result.current.critiqueHook.error).toBeNull();
    expect(result.current.editor.proposal.status).toBe("idle");
  });

  it("hides the critique once the analysis it came from is gone", async () => {
    installCritiqueMock();
    const { result, rerender } = renderCritique();

    await act(async () => {
      await result.current.critiqueHook.request();
    });
    expect(result.current.critiqueHook.critique).not.toBeNull();

    rerender({
      analysis: analysisState({
        analysisId: "99999999-9999-4999-9999-999999999999",
        report: analysisReport({
          analysisId: "99999999-9999-4999-9999-999999999999",
        }),
      }),
    });

    expect(result.current.critiqueHook.critique).toBeNull();
    expect(result.current.critiqueHook.canRequest).toBe(true);
  });

  it("reports a failed critique without blocking the next request", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(
          {
            error: {
              code: "provider_unavailable",
              message: "点评服务暂不可用。",
              details: {},
            },
          },
          503,
        ),
      ),
    );
    const { result } = renderCritique();

    let loaded = true;
    await act(async () => {
      loaded = await result.current.critiqueHook.request();
    });

    expect(loaded).toBe(false);
    expect(result.current.critiqueHook.pending).toBe(false);
    expect(result.current.critiqueHook.error?.code).toBe("provider_unavailable");
    expect(result.current.critiqueHook.canRequest).toBe(true);
    expect(result.current.editor.proposal.status).toBe("idle");
  });

  it("refuses to request without a report for the loaded image", async () => {
    const calls = installCritiqueMock();
    const { result } = renderCritique(
      readyEditorState(),
      analysisState({
        analysisId: null,
        report: null,
        status: null,
        stage: null,
      }),
    );

    expect(result.current.critiqueHook.canRequest).toBe(false);
    let loaded = true;
    await act(async () => {
      loaded = await result.current.critiqueHook.request();
    });

    expect(loaded).toBe(false);
    expect(calls.critiques).toHaveLength(0);
  });

  it("ignores a second request while the first is still running", async () => {
    const calls = installCritiqueMock({ gateCritique: true });
    const { result } = renderCritique();

    let first: Promise<boolean> | null = null;
    act(() => {
      first = result.current.critiqueHook.request();
    });
    await waitFor(() => expect(calls.critiques).toHaveLength(1));

    expect(result.current.critiqueHook.pending).toBe(true);
    expect(result.current.critiqueHook.canRequest).toBe(false);
    let second = true;
    await act(async () => {
      second = await result.current.critiqueHook.request();
    });
    expect(second).toBe(false);
    expect(calls.critiques).toHaveLength(1);

    calls.releaseCritique();
    await act(async () => {
      await first;
    });
    expect(result.current.critiqueHook.pending).toBe(false);
  });

  it("previews an actionable suggestion through the proposal slice", async () => {
    const calls = installCritiqueMock();
    const before = readyEditorState();
    const { result } = renderCritique();

    await act(async () => {
      await result.current.critiqueHook.request();
    });

    let applied = false;
    await act(async () => {
      applied = await result.current.critiqueHook.apply(actionableSuggestion());
    });

    expect(applied).toBe(true);
    expect(calls.applies).toHaveLength(1);
    expect(calls.applies[0]).toMatchObject({
      sessionId: SESSION_ID,
      patch: { highlights: -20, whites: -8 },
    });
    expect(result.current.editor.proposal.source).toBe("critique");
    expect(result.current.editor.proposal.patch?.patchId).toBe(PATCH_ID);
    expect(result.current.editor.proposal.recipe?.adjustments.highlights).toBe(
      -20,
    );
    // Nothing is persisted yet: the draft is untouched and the accept path is armed.
    expect(result.current.editor.draft).toEqual(before.draft);
    expect(selectCanAcceptProposal(result.current.editor)).toBe(true);
    // A critique preview is never persisted, so it offers no chat anchor.
    expect(selectProposalAnchorId(result.current.editor.proposal)).toBeNull();
  });

  it("does not preview a suggestion that carries no parameters", async () => {
    const calls = installCritiqueMock();
    const { result } = renderCritique();

    const staticAdvice = photographerCritique().suggestions[1];
    expect(isActionableSuggestion(staticAdvice)).toBe(false);

    let applied = true;
    await act(async () => {
      applied = await result.current.critiqueHook.apply(staticAdvice);
    });

    expect(applied).toBe(false);
    expect(calls.applies).toHaveLength(0);
    expect(result.current.editor.proposal.status).toBe("idle");
  });

  it("keeps the preview errored when the apply call fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).endsWith("/critique/apply")) {
          return jsonResponse(
            {
              error: {
                code: "photographer_recipe_invalid",
                message: "调整后的配方未通过校验。",
                details: {},
              },
            },
            422,
          );
        }
        return jsonResponse(photographerCritique());
      }),
    );
    const { result } = renderCritique();

    await act(async () => {
      await result.current.critiqueHook.request();
    });
    let applied = true;
    await act(async () => {
      applied = await result.current.critiqueHook.apply(
        actionableSuggestion(),
      );
    });

    expect(applied).toBe(false);
    expect(result.current.critiqueHook.applying).toBe(false);
    expect(result.current.editor.proposal.status).toBe("error");
    expect(result.current.editor.proposal.error?.code).toBe(
      "photographer_recipe_invalid",
    );
  });

  it("drops the critique but keeps the preview on clear", async () => {
    installCritiqueMock();
    const { result } = renderCritique();

    await act(async () => {
      await result.current.critiqueHook.request();
    });
    await act(async () => {
      await result.current.critiqueHook.apply(actionableSuggestion());
    });

    act(() => {
      result.current.critiqueHook.clear();
    });

    expect(result.current.critiqueHook.critique).toBeNull();
    expect(result.current.editor.proposal.status).toBe("ready");
    expect(result.current.editor.proposal.source).toBe("critique");
  });

  it("refuses to apply before a session is loaded", async () => {
    const calls = installCritiqueMock();
    const { result } = renderCritique(createInitialEditorState());

    expect(result.current.critiqueHook.canApply).toBe(false);
    let applied = true;
    await act(async () => {
      applied = await result.current.critiqueHook.apply(
        actionableSuggestion(),
      );
    });

    expect(applied).toBe(false);
    expect(calls.applies).toHaveLength(0);
  });
});
