import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { UseAnalysisResult } from "@/features/analysis/hooks/use-analysis";
import {
  EditorProvider,
  useEditorState,
} from "@/features/editor/state/editor-context";
import {
  editorReducer,
  isChatPatch,
  type EditorState,
} from "@/features/editor/state/editor-reducer";
import { usePhotographerChat } from "@/features/photographer/hooks/use-photographer-chat";
import type { PhotographerPatchResponse } from "@/types/photographer";
import { ANALYSIS_ID, analysisReport } from "./analysis-fixtures";
import {
  PATCH_ID,
  PLAN_ID,
  photographerPatch,
  photographerPlan,
  unsupportedPatch,
} from "./photographer-fixtures";
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
    startedAt: null,
    running: false,
    start: vi.fn(),
    retry: vi.fn(),
    rerun: vi.fn(),
    ...overrides,
  };
}

interface ChatCalls {
  chats: Array<Record<string, unknown>>;
  plans: Array<Record<string, unknown>>;
  releaseChat: () => void;
}

/** `gateChat` holds the patch response open so a test can act mid-flight. */
function installChatMock(
  patch: PhotographerPatchResponse = photographerPatch(),
  gateChat = false,
): ChatCalls {
  const calls: ChatCalls = {
    chats: [],
    plans: [],
    releaseChat: () => {},
  };
  let open = !gateChat;
  const gate = new Promise<void>((resolve) => {
    calls.releaseChat = () => {
      open = true;
      resolve();
    };
  });

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (
        url.endsWith("/api/v1/ai/photographer/plan") &&
        init?.method === "POST"
      ) {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        calls.plans.push(body);
        return jsonResponse(
          photographerPlan({
            sessionId: SESSION_ID,
            imageId: IMAGE_ID,
            analysisId: ANALYSIS_ID,
          }),
        );
      }
      if (
        url.endsWith("/api/v1/ai/photographer/chat") &&
        init?.method === "POST"
      ) {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        calls.chats.push(body);
        if (!open) {
          await gate;
        }
        return jsonResponse(patch);
      }
      return jsonResponse(
        { error: { code: "not_found", message: "Not found", details: {} } },
        404,
      );
    }),
  );
  return calls;
}

function withState(state: EditorState) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <EditorProvider initialState={state}>{children}</EditorProvider>;
  };
}

function renderChat(
  state: EditorState = readyEditorState(),
  analysis: UseAnalysisResult = analysisState(),
) {
  return renderHook(
    () => ({ chat: usePhotographerChat(analysis), editor: useEditorState() }),
    { wrapper: withState(state) },
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("usePhotographerChat", () => {
  it("builds the anchor plan from the analysis when nothing is on screen", async () => {
    const calls = installChatMock();
    const { result } = renderChat();

    let accepted = false;
    await act(async () => {
      accepted = await result.current.chat.send("  降低饱和度  ");
    });

    expect(accepted).toBe(true);
    expect(calls.plans).toHaveLength(1);
    expect(calls.plans[0]).toMatchObject({
      sessionId: SESSION_ID,
      analysisId: ANALYSIS_ID,
      mode: "auto",
    });
    expect(calls.chats[0]).toMatchObject({
      planId: PLAN_ID,
      instruction: "降低饱和度",
    });
    expect(result.current.editor.proposal.source).toBe("chat");
    expect(result.current.editor.proposal.plan).toBeNull();
    expect(result.current.editor.proposal.patch?.patchId).toBe(PATCH_ID);
    expect(result.current.editor.proposal.recipe?.adjustments.saturation).toBe(
      -8,
    );
    expect(result.current.chat.turns).toHaveLength(1);
    expect(result.current.chat.turns[0]).toMatchObject({
      instruction: "降低饱和度",
      pending: false,
      failed: false,
    });
    expect(result.current.chat.turns[0].reply).toBe(photographerPatch().reason);
  });

  it("reuses the plan already on screen instead of planning again", async () => {
    const calls = installChatMock();
    const { result } = renderChat(
      editorReducer(readyEditorState(), {
        type: "proposal-ready",
        plan: photographerPlan(),
      }),
    );

    await act(async () => {
      await result.current.chat.send("整体更暖一点");
    });

    expect(calls.plans).toHaveLength(0);
    expect(calls.chats[0]).toMatchObject({ planId: PLAN_ID });
  });

  it("chains the next instruction onto the newest patch id", async () => {
    const calls = installChatMock();
    const { result } = renderChat();

    await act(async () => {
      await result.current.chat.send("降低饱和度");
    });
    await act(async () => {
      await result.current.chat.send("再提高一点对比");
    });

    expect(calls.plans).toHaveLength(1);
    expect(calls.chats).toHaveLength(2);
    expect(calls.chats[0]).toMatchObject({ planId: PLAN_ID });
    expect(calls.chats[1]).toMatchObject({
      planId: PATCH_ID,
      instruction: "再提高一点对比",
    });
    expect(result.current.chat.turns.map((turn) => turn.instruction)).toEqual([
      "降低饱和度",
      "再提高一点对比",
    ]);
  });

  it("keeps an unsupported instruction visible without touching the draft", async () => {
    const calls = installChatMock(unsupportedPatch());
    const before = readyEditorState();
    const { result } = renderChat(before);

    let accepted = true;
    await act(async () => {
      accepted = await result.current.chat.send("删除背景里的人物");
    });

    expect(accepted).toBe(false);
    expect(result.current.editor.proposal.status).toBe("ready");
    const refused = result.current.editor.proposal.patch;
    expect(
      refused !== null && isChatPatch(refused) && !refused.supported,
    ).toBe(true);
    expect(result.current.editor.proposal.patch?.changes).toHaveLength(0);
    expect(result.current.editor.draft).toEqual(before.draft);
    expect(result.current.chat.turns[0].failed).toBe(false);
    expect(result.current.chat.turns[0].reply).toBe(unsupportedPatch().reason);
    expect(calls.chats).toHaveLength(1);
  });

  it("reports a failed send and leaves the previous proposal errored", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).endsWith("/api/v1/ai/photographer/plan")) {
          return jsonResponse(photographerPlan());
        }
        return jsonResponse(
          {
            error: {
              code: "provider_unavailable",
              message: "Planner 服务暂不可用。",
              details: {},
            },
          },
          503,
        );
      }),
    );
    const { result } = renderChat();

    let accepted = true;
    await act(async () => {
      accepted = await result.current.chat.send("降低饱和度");
    });

    expect(accepted).toBe(false);
    expect(result.current.chat.pending).toBe(false);
    expect(result.current.chat.error?.code).toBe("provider_unavailable");
    expect(result.current.editor.proposal.status).toBe("error");
    expect(result.current.editor.proposal.error?.code).toBe(
      "provider_unavailable",
    );
    expect(result.current.chat.turns[0]).toMatchObject({
      pending: false,
      failed: true,
    });
  });

  it("refuses to send without a session anchor or an analysis", async () => {
    const calls = installChatMock();
    const { result } = renderChat(
      readyEditorState(),
      analysisState({
        analysisId: null,
        report: null,
        status: null,
        stage: null,
      }),
    );

    expect(result.current.chat.canSend).toBe(false);
    let accepted = true;
    await act(async () => {
      accepted = await result.current.chat.send("降低饱和度");
    });

    expect(accepted).toBe(false);
    expect(calls.chats).toHaveLength(0);
    expect(calls.plans).toHaveLength(0);
  });

  it("ignores a second instruction while the first is still running", async () => {
    const calls = installChatMock(photographerPatch(), true);
    const { result } = renderChat();

    let first: Promise<boolean> | null = null;
    act(() => {
      first = result.current.chat.send("降低饱和度");
    });
    await waitFor(() => expect(calls.chats).toHaveLength(1));

    expect(result.current.chat.pending).toBe(true);
    expect(result.current.chat.canSend).toBe(false);
    let second = true;
    await act(async () => {
      second = await result.current.chat.send("再提高一点对比");
    });
    expect(second).toBe(false);
    expect(calls.chats).toHaveLength(1);

    calls.releaseChat();
    await act(async () => {
      await first;
    });
    expect(result.current.chat.pending).toBe(false);
  });

  it("clears the transcript and the proposal on reset", async () => {
    installChatMock();
    const { result } = renderChat();

    await act(async () => {
      await result.current.chat.send("降低饱和度");
    });
    expect(result.current.chat.turns).toHaveLength(1);

    act(() => {
      result.current.chat.reset();
    });

    expect(result.current.chat.turns).toHaveLength(0);
    expect(result.current.chat.error).toBeNull();
    expect(result.current.editor.proposal.status).toBe("idle");
    expect(result.current.editor.proposal.patch).toBeNull();
  });

  it("keeps the transcript bounded to the latest turns", async () => {
    installChatMock();
    const { result } = renderChat();

    for (let index = 0; index < 9; index += 1) {
      await act(async () => {
        await result.current.chat.send(`降低饱和度 ${index + 1}`);
      });
    }

    expect(result.current.chat.turns).toHaveLength(8);
    expect(result.current.chat.turns[0].instruction).toBe("降低饱和度 2");
    expect(result.current.chat.turns[7].instruction).toBe("降低饱和度 9");
  });
});
