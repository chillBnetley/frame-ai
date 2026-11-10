"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { UseAnalysisResult } from "@/features/analysis/hooks/use-analysis";
import { useSessionActions } from "@/features/editor/hooks/use-session";
import {
  useEditorDispatch,
  useEditorState,
} from "@/features/editor/state/editor-context";
import {
  selectCanAcceptProposal,
  type EditorProposal,
  type ProposalView,
} from "@/features/editor/state/editor-reducer";
import { createPlan } from "@/lib/api/photographer";
import { describeEditorError } from "@/lib/error-messages";
import {
  useFeedback,
  type UseFeedbackResult,
} from "@/features/photographer/hooks/use-feedback";
import type {
  FeedbackSource,
  PhotographerPlanRequest,
  PhotographerStyle,
} from "@/types/photographer";

const DEFAULT_STYLE_STRENGTH = 0.5;

interface StyleSelection {
  styleId: string | null;
  strength: number;
  /** True while the slider is being dragged: the plan is only re-requested on commit. */
  pendingCommit: boolean;
}

export interface UsePhotographerResult {
  proposal: EditorProposal;
  canAccept: boolean;
  styleId: string | null;
  styleStrength: number;
  feedback: UseFeedbackResult;
  start: () => void;
  selectStyle: (style: PhotographerStyle | null) => void;
  setStyleStrength: (value: number) => void;
  commitStyleStrength: () => void;
  retry: () => void;
  cancel: () => void;
  showView: (view: ProposalView) => void;
  accept: () => Promise<boolean>;
  abandon: () => Promise<void>;
}

const INITIAL_SELECTION: StyleSelection = {
  styleId: null,
  strength: DEFAULT_STYLE_STRENGTH,
  pendingCommit: false,
};

function clampStrength(value: number): number {
  if (!Number.isFinite(value)) {
    return DEFAULT_STYLE_STRENGTH;
  }
  return Math.min(1, Math.max(0, Math.round(value * 100) / 100));
}

/**
 * The stored plan a decision refers to. A critique preview is never persisted,
 * so it is recorded with its source but without a plan reference.
 */
function proposalTarget(
  proposal: EditorProposal,
): { source: FeedbackSource | null; planId: string | null } {
  if (proposal.source === "plan") {
    return { source: proposal.source, planId: proposal.plan?.planId ?? null };
  }
  if (proposal.source === "chat") {
    return { source: proposal.source, planId: proposal.patch?.patchId ?? null };
  }
  if (proposal.source === "critique") {
    return { source: proposal.source, planId: null };
  }
  return { source: null, planId: null };
}

export function usePhotographer(
  analysis: UseAnalysisResult,
): UsePhotographerResult {
  const state = useEditorState();
  const dispatch = useEditorDispatch();
  const { acceptProposal } = useSessionActions();
  const autoPlanRef = useRef(false);
  const requestRef = useRef(0);
  const controllerRef = useRef<AbortController | null>(null);
  /** The selection the most recent plan request was built from, or null before the first plan. */
  const appliedRef = useRef<{
    styleId: string | null;
    strength: number;
  } | null>(null);
  const selectionRef = useRef<StyleSelection>(INITIAL_SELECTION);
  const [selection, setSelection] = useState<StyleSelection>(INITIAL_SELECTION);

  const sessionId = state.sessionId;
  const feedback = useFeedback(sessionId);
  const imageId = state.imageId;
  const report =
    analysis.report !== null &&
    imageId !== null &&
    analysis.report.image.id === imageId
      ? analysis.report
      : null;

  useEffect(() => {
    autoPlanRef.current = false;
    requestRef.current += 1;
    controllerRef.current?.abort();
    controllerRef.current = null;
    appliedRef.current = null;
  }, [sessionId]);

  useEffect(
    () => () => {
      requestRef.current += 1;
      controllerRef.current?.abort();
    },
    [],
  );

  const applySelection = useCallback((next: StyleSelection) => {
    selectionRef.current = next;
    setSelection(next);
  }, []);

  const requestPlan = useCallback(
    async (analysisId: string): Promise<void> => {
      if (sessionId === null) {
        return;
      }
      const current = selectionRef.current;
      const request: PhotographerPlanRequest = {
        sessionId,
        analysisId,
        lockedFields: [],
        ...(current.styleId === null
          ? { mode: "auto" as const }
          : {
              mode: "style" as const,
              styleId: current.styleId,
              styleStrength: current.strength,
            }),
      };
      appliedRef.current = {
        styleId: current.styleId,
        strength: current.strength,
      };
      const requestNumber = requestRef.current + 1;
      requestRef.current = requestNumber;
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      dispatch({ type: "proposal-loading" });

      try {
        const plan = await createPlan(request, controller.signal);
        if (requestNumber !== requestRef.current || controller.signal.aborted) {
          return;
        }
        dispatch({ type: "proposal-ready", plan });
      } catch (error) {
        if (requestNumber !== requestRef.current || controller.signal.aborted) {
          return;
        }
        dispatch({ type: "proposal-error", error: describeEditorError(error) });
      }
    },
    [dispatch, sessionId],
  );

  const start = useCallback(() => {
    if (sessionId === null || state.proposal.status === "loading") {
      return;
    }
    if (report !== null) {
      void requestPlan(report.analysisId);
      return;
    }
    autoPlanRef.current = true;
    if (!analysis.running) {
      analysis.start(false);
    }
  }, [analysis, report, requestPlan, sessionId, state.proposal.status]);

  useEffect(() => {
    if (!autoPlanRef.current) {
      return;
    }
    if (report !== null) {
      autoPlanRef.current = false;
      void requestPlan(report.analysisId);
      return;
    }
    if (analysis.running) {
      return;
    }
    // A deduplicated analysis can report "completed" one tick before its report
    // arrives; keep waiting instead of treating that window as a failure.
  }, [analysis.error, analysis.running, report, requestPlan]);

  // A style or strength change re-generates the proposal; it is never accepted
  // implicitly, so the user still confirms through the preview.
  useEffect(() => {
    const applied = appliedRef.current;
    if (
      applied === null ||
      selection.pendingCommit ||
      report === null ||
      (applied.styleId === selection.styleId &&
        applied.strength === selection.strength)
    ) {
      return;
    }
    if (
      state.proposal.status !== "ready" &&
      state.proposal.status !== "error"
    ) {
      return;
    }
    void requestPlan(report.analysisId);
  }, [report, requestPlan, selection, state.proposal.status]);

  const selectStyle = useCallback(
    (style: PhotographerStyle | null) => {
      const current = selectionRef.current;
      if (style === null) {
        if (current.styleId === null) {
          return;
        }
        applySelection({ ...current, styleId: null, pendingCommit: false });
        return;
      }
      if (current.styleId === style.id) {
        return;
      }
      applySelection({
        styleId: style.id,
        strength: clampStrength(style.defaultStrength),
        pendingCommit: false,
      });
    },
    [applySelection],
  );

  const setStyleStrength = useCallback(
    (value: number) => {
      const current = selectionRef.current;
      const strength = clampStrength(value);
      if (current.strength === strength) {
        return;
      }
      applySelection({ ...current, strength, pendingCommit: true });
    },
    [applySelection],
  );

  const commitStyleStrength = useCallback(() => {
    const current = selectionRef.current;
    if (!current.pendingCommit) {
      return;
    }
    applySelection({ ...current, pendingCommit: false });
  }, [applySelection]);

  const cancel = useCallback(() => {
    requestRef.current += 1;
    controllerRef.current?.abort();
    controllerRef.current = null;
    autoPlanRef.current = false;
    appliedRef.current = null;
    dispatch({ type: "proposal-clear" });
  }, [dispatch]);

  const retry = useCallback(() => {
    start();
  }, [start]);

  const showView = useCallback(
    (view: ProposalView) => {
      dispatch({ type: "proposal-view", view });
    },
    [dispatch],
  );

  const accept = useCallback(async (): Promise<boolean> => {
    const source = state.proposal.plan ?? state.proposal.patch;
    if (source === null || !selectCanAcceptProposal(state)) {
      return false;
    }
    const outcome = await acceptProposal(source.recipe);
    if (!outcome.ok) {
      return false;
    }
    await feedback.recordAndAskForRating({
      action: "accepted",
      revisionId: outcome.revisionId,
      ...proposalTarget(state.proposal),
    });
    return true;
  }, [acceptProposal, feedback, state]);

  const abandon = useCallback(async (): Promise<void> => {
    const proposal = state.proposal;
    const recorded = proposal.status === "ready" && proposal.source !== null;
    appliedRef.current = null;
    dispatch({ type: "proposal-clear" });
    if (!recorded) {
      return;
    }
    await feedback.record({
      action: "rejected",
      revisionId: null,
      ...proposalTarget(proposal),
    });
  }, [dispatch, feedback, state.proposal]);

  return {
    proposal: state.proposal,
    canAccept: selectCanAcceptProposal(state),
    styleId: selection.styleId,
    styleStrength: selection.strength,
    feedback,
    start,
    selectStyle,
    setStyleStrength,
    commitStyleStrength,
    retry,
    cancel,
    showView,
    accept,
    abandon,
  };
}
