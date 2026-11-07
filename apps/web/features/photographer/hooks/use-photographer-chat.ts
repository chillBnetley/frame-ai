"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { UseAnalysisResult } from "@/features/analysis/hooks/use-analysis";
import {
  useEditorDispatch,
  useEditorState,
} from "@/features/editor/state/editor-context";
import { selectProposalAnchorId } from "@/features/editor/state/editor-reducer";
import { createPlan, sendChat } from "@/lib/api/photographer";
import { describeEditorError, type EditorError } from "@/lib/error-messages";

const MAX_TURNS = 8;

export interface ChatTurn {
  id: string;
  instruction: string;
  reply: string | null;
  pending: boolean;
  failed: boolean;
}

export interface UsePhotographerChatResult {
  turns: ChatTurn[];
  pending: boolean;
  error: EditorError | null;
  canSend: boolean;
  send: (instruction: string) => Promise<boolean>;
  reset: () => void;
}

interface ChatHistory {
  sessionId: string | null;
  turns: ChatTurn[];
  pending: boolean;
  error: EditorError | null;
}

const EMPTY_HISTORY: ChatHistory = {
  sessionId: null,
  turns: [],
  pending: false,
  error: null,
};

export function usePhotographerChat(
  analysis: UseAnalysisResult,
): UsePhotographerChatResult {
  const state = useEditorState();
  const dispatch = useEditorDispatch();
  const [history, setHistory] = useState<ChatHistory>(EMPTY_HISTORY);
  const counterRef = useRef(0);
  const controllerRef = useRef<AbortController | null>(null);
  const inFlightRef = useRef(false);

  const sessionId = state.sessionId;
  const imageId = state.imageId;
  const anchorId = selectProposalAnchorId(state.proposal);
  const analysisId =
    analysis.report !== null &&
    imageId !== null &&
    analysis.report.image.id === imageId
      ? analysis.report.analysisId
      : null;
  // Turns belong to the session they were typed in; a new image starts a clean
  // transcript without needing an effect.
  const current = history.sessionId === sessionId ? history : EMPTY_HISTORY;

  useEffect(
    () => () => {
      controllerRef.current?.abort();
      inFlightRef.current = false;
    },
    [],
  );

  const patchTurn = useCallback((id: string, changes: Partial<ChatTurn>) => {
    setHistory((previous) => ({
      ...previous,
      turns: previous.turns.map((turn) =>
        turn.id === id ? { ...turn, ...changes, pending: false } : turn,
      ),
    }));
  }, []);

  const send = useCallback(
    async (raw: string): Promise<boolean> => {
      const instruction = raw.trim();
      const anchor = anchorId;
      const targetAnalysisId = analysisId;
      if (
        instruction === "" ||
        inFlightRef.current ||
        sessionId === null ||
        (anchor === null && targetAnalysisId === null)
      ) {
        return false;
      }

      counterRef.current += 1;
      const turnId = `turn-${counterRef.current}`;
      inFlightRef.current = true;
      setHistory((previous) => ({
        sessionId,
        error: null,
        pending: true,
        turns: [
          ...(previous.sessionId === sessionId ? previous.turns : []),
          {
            id: turnId,
            instruction,
            reply: null,
            pending: true,
            failed: false,
          },
        ].slice(-MAX_TURNS),
      }));

      const controller = new AbortController();
      controllerRef.current?.abort();
      controllerRef.current = controller;
      dispatch({ type: "proposal-loading" });

      try {
        // POST /chat anchors on a plan id, so the patch applies to the recipe
        // the user is looking at. With no proposal on screen yet, build that
        // anchor from the current analysis instead of asking for a plan first.
        let planId = anchor;
        if (planId === null) {
          const plan = await createPlan(
            { sessionId, analysisId: targetAnalysisId, mode: "auto" },
            controller.signal,
          );
          planId = plan.planId;
        }
        const patch = await sendChat(
          { planId, instruction },
          controller.signal,
        );
        if (controller.signal.aborted) {
          return false;
        }
        dispatch({ type: "patch-ready", patch });
        // A refused instruction is an answered turn, not a failed request.
        patchTurn(turnId, { reply: patch.reason, failed: false });
        return patch.supported && patch.changes.length > 0;
      } catch (caught) {
        if (controller.signal.aborted) {
          return false;
        }
        const described = describeEditorError(caught);
        setHistory((previous) => ({ ...previous, error: described }));
        dispatch({ type: "proposal-error", error: described });
        patchTurn(turnId, { failed: true });
        return false;
      } finally {
        inFlightRef.current = false;
        setHistory((previous) => ({ ...previous, pending: false }));
      }
    },
    [analysisId, anchorId, dispatch, patchTurn, sessionId],
  );

  const reset = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    inFlightRef.current = false;
    setHistory((previous) => ({
      ...previous,
      pending: false,
      error: null,
      turns: [],
    }));
    dispatch({ type: "proposal-clear" });
  }, [dispatch]);

  return {
    turns: current.turns,
    pending: current.pending,
    error: current.error,
    canSend:
      sessionId !== null &&
      !current.pending &&
      (anchorId !== null || analysisId !== null),
    send,
    reset,
  };
}
