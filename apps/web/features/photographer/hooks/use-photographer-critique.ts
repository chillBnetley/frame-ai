"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { UseAnalysisResult } from "@/features/analysis/hooks/use-analysis";
import {
  useEditorDispatch,
  useEditorState,
} from "@/features/editor/state/editor-context";
import {
  applyCritique,
  fetchCritique,
} from "@/lib/api/photographer";
import { describeEditorError, type EditorError } from "@/lib/error-messages";
import type {
  PhotographerCritique,
  PhotographerCritiqueSuggestion,
} from "@/types/photographer";

export interface UsePhotographerCritiqueResult {
  critique: PhotographerCritique | null;
  pending: boolean;
  applying: boolean;
  error: EditorError | null;
  canRequest: boolean;
  canApply: boolean;
  request: () => Promise<boolean>;
  apply: (suggestion: PhotographerCritiqueSuggestion) => Promise<boolean>;
  clear: () => void;
}

interface CritiqueState {
  analysisId: string | null;
  critique: PhotographerCritique | null;
  pending: boolean;
  applying: boolean;
  error: EditorError | null;
}

const EMPTY: CritiqueState = {
  analysisId: null,
  critique: null,
  pending: false,
  applying: false,
  error: null,
};

/** A suggestion is actionable once it carries at least one parameter value. */
export function isActionableSuggestion(
  suggestion: PhotographerCritiqueSuggestion,
): boolean {
  const patch = suggestion.recipePatch;
  if (patch === null || patch === undefined) {
    return false;
  }
  return Object.values(patch).some((value) => value !== null);
}

export function usePhotographerCritique(
  analysis: UseAnalysisResult,
): UsePhotographerCritiqueResult {
  const state = useEditorState();
  const dispatch = useEditorDispatch();
  const [data, setData] = useState<CritiqueState>(EMPTY);
  const controllerRef = useRef<AbortController | null>(null);
  const inFlightRef = useRef(false);

  const sessionId = state.sessionId;
  const imageId = state.imageId;
  const analysisId =
    analysis.report !== null &&
    imageId !== null &&
    analysis.report.image.id === imageId
      ? analysis.report.analysisId
      : null;
  // A critique belongs to the report it was derived from; a new analysis shows
  // no critique without needing an effect.
  const current = data.analysisId === analysisId ? data : EMPTY;

  useEffect(
    () => () => {
      controllerRef.current?.abort();
      inFlightRef.current = false;
    },
    [],
  );

  const start = useCallback(
    (changes: Partial<CritiqueState>) => {
      setData((previous) => ({
        ...(previous.analysisId === analysisId ? previous : EMPTY),
        analysisId,
        error: null,
        ...changes,
      }));
    },
    [analysisId],
  );

  const request = useCallback(async (): Promise<boolean> => {
    if (analysisId === null || inFlightRef.current) {
      return false;
    }
    inFlightRef.current = true;
    start({ pending: true });

    const controller = new AbortController();
    controllerRef.current?.abort();
    controllerRef.current = controller;

    try {
      const critique = await fetchCritique({ analysisId }, controller.signal);
      if (controller.signal.aborted) {
        return false;
      }
      setData((previous) => ({
        ...(previous.analysisId === analysisId ? previous : EMPTY),
        analysisId,
        critique,
        pending: false,
        applying: false,
        error: null,
      }));
      return true;
    } catch (caught) {
      if (controller.signal.aborted) {
        return false;
      }
      setData((previous) => ({
        ...(previous.analysisId === analysisId ? previous : EMPTY),
        analysisId,
        critique: null,
        pending: false,
        applying: false,
        error: describeEditorError(caught),
      }));
      return false;
    } finally {
      inFlightRef.current = false;
    }
  }, [analysisId, start]);

  const apply = useCallback(
    async (suggestion: PhotographerCritiqueSuggestion): Promise<boolean> => {
      const patch = suggestion.recipePatch;
      if (
        sessionId === null ||
        patch === null ||
        patch === undefined ||
        inFlightRef.current
      ) {
        return false;
      }
      inFlightRef.current = true;
      start({ applying: true });

      const controller = new AbortController();
      controllerRef.current?.abort();
      controllerRef.current = controller;
      dispatch({ type: "proposal-loading" });

      try {
        const result = await applyCritique(
          { sessionId, patch },
          controller.signal,
        );
        if (controller.signal.aborted) {
          return false;
        }
        dispatch({ type: "critique-ready", patch: result });
        setData((previous) => ({
          ...(previous.analysisId === analysisId ? previous : EMPTY),
          analysisId,
          applying: false,
          pending: false,
          error: null,
        }));
        return result.changes.length > 0;
      } catch (caught) {
        if (controller.signal.aborted) {
          return false;
        }
        const described = describeEditorError(caught);
        setData((previous) => ({
          ...(previous.analysisId === analysisId ? previous : EMPTY),
          analysisId,
          applying: false,
          pending: false,
          error: described,
        }));
        dispatch({ type: "proposal-error", error: described });
        return false;
      } finally {
        inFlightRef.current = false;
      }
    },
    [analysisId, dispatch, sessionId, start],
  );

  const clear = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    inFlightRef.current = false;
    setData((previous) => ({
      ...previous,
      critique: null,
      pending: false,
      applying: false,
      error: null,
    }));
  }, []);

  return {
    critique: current.critique,
    pending: current.pending,
    applying: current.applying,
    error: current.error,
    canRequest: analysisId !== null && !current.pending,
    canApply:
      sessionId !== null &&
      analysisId !== null &&
      !current.pending &&
      !current.applying,
    request,
    apply,
    clear,
  };
}
