"use client";

import { useCallback, useEffect, useRef } from "react";

import { useEditorDispatch, useEditorState } from "@/features/editor/state/editor-context";
import type { PreviewState } from "@/features/editor/state/editor-reducer";
import { renderPreview } from "@/lib/api/sessions";
import { describeEditorError, isSilentEditorError } from "@/lib/error-messages";
import { recipeFingerprint } from "@/lib/recipe";
import { nextRenderSeq } from "@/lib/render-seq";
import type { EditRecipe } from "@/types/session";

export const PREVIEW_DEBOUNCE_MS = 250;
export const PREVIEW_MAX_WAIT_MS = 600;

export interface UseRenderPreviewOptions {
  debounceMs?: number;
  maxWaitMs?: number;
}

export interface UseRenderPreviewResult {
  preview: PreviewState;
  requestFinal: () => Promise<void>;
  retry: () => Promise<void>;
  cancel: () => void;
}

interface InflightRender {
  fingerprint: string;
  quality: "draft" | "final";
}

export function useRenderPreview(
  options: UseRenderPreviewOptions = {},
): UseRenderPreviewResult {
  const {
    debounceMs = PREVIEW_DEBOUNCE_MS,
    maxWaitMs = PREVIEW_MAX_WAIT_MS,
  } = options;
  const state = useEditorState();
  const dispatch = useEditorDispatch();
  const { sessionId, draft, phase } = state;
  const ready = phase === "ready";
  const fingerprint = recipeFingerprint(draft);

  const seqRef = useRef(0);
  const controllerRef = useRef<AbortController | null>(null);
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const maxWaitTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const renderedFingerprintRef = useRef<string | null>(null);
  const completedFinalFingerprintRef = useRef<string | null>(null);
  const inflightRef = useRef<InflightRender | null>(null);
  const renderedSessionRef = useRef<string | null>(null);
  const draftRef = useRef(draft);
  const fingerprintRef = useRef(fingerprint);

  useEffect(() => {
    draftRef.current = draft;
    fingerprintRef.current = fingerprint;
  }, [draft, fingerprint]);

  const clearDraftTimers = useCallback(() => {
    if (debounceTimerRef.current !== null) {
      clearTimeout(debounceTimerRef.current);
      debounceTimerRef.current = null;
    }
    if (maxWaitTimerRef.current !== null) {
      clearTimeout(maxWaitTimerRef.current);
      maxWaitTimerRef.current = null;
    }
  }, []);

  const perform = useCallback(
    async (
      quality: "draft" | "final",
      recipe: EditRecipe,
    ): Promise<void> => {
      if (!ready || sessionId === null) {
        return;
      }

      const requestFingerprint = recipeFingerprint(recipe);
      const inflight = inflightRef.current;
      if (
        inflight !== null &&
        inflight.fingerprint === requestFingerprint &&
        inflight.quality === quality
      ) {
        return;
      }

      const seq = nextRenderSeq();
      seqRef.current = seq;
      const request: InflightRender = {
        fingerprint: requestFingerprint,
        quality,
      };
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      inflightRef.current = request;
      dispatch({ type: "preview-loading", seq });

      try {
        const result = await renderPreview(
          sessionId,
          { recipe, quality },
          controller.signal,
          seq,
        );
        if (controller.signal.aborted || seq !== seqRef.current) {
          return;
        }
        dispatch({
          type: "preview-ready",
          seq,
          url: result.previewUrl,
          width: result.width,
          height: result.height,
          quality: result.quality,
          warnings: result.warnings ?? [],
        });
        if (quality === "final") {
          completedFinalFingerprintRef.current = requestFingerprint;
        }
      } catch (error) {
        if (controller.signal.aborted || seq !== seqRef.current) {
          return;
        }
        const normalized = describeEditorError(error);
        dispatch({
          type: "preview-error",
          seq,
          error: isSilentEditorError(normalized.code)
            ? { ...normalized, message: "" }
            : normalized,
        });
      } finally {
        if (inflightRef.current === request) {
          inflightRef.current = null;
        }
      }
    },
    [dispatch, ready, sessionId],
  );

  const fireDraft = useCallback(() => {
    clearDraftTimers();
    const nextFingerprint = fingerprintRef.current;
    if (renderedFingerprintRef.current === nextFingerprint) {
      return;
    }
    renderedFingerprintRef.current = nextFingerprint;
    void perform("draft", draftRef.current);
  }, [clearDraftTimers, perform]);

  const scheduleDraft = useCallback(() => {
    if (debounceTimerRef.current !== null) {
      clearTimeout(debounceTimerRef.current);
    }
    debounceTimerRef.current = setTimeout(() => {
      debounceTimerRef.current = null;
      fireDraft();
    }, debounceMs);
    if (maxWaitTimerRef.current === null) {
      maxWaitTimerRef.current = setTimeout(() => {
        maxWaitTimerRef.current = null;
        fireDraft();
      }, maxWaitMs);
    }
  }, [debounceMs, fireDraft, maxWaitMs]);

  useEffect(() => {
    if (renderedSessionRef.current !== sessionId) {
      renderedSessionRef.current = sessionId;
      renderedFingerprintRef.current = null;
      completedFinalFingerprintRef.current = null;
      inflightRef.current = null;
      controllerRef.current?.abort();
      clearDraftTimers();
    }
    if (!sessionId || phase !== "ready") {
      return;
    }
    if (renderedFingerprintRef.current === fingerprint) {
      return;
    }

    const isFirstRender = renderedFingerprintRef.current === null;
    if (isFirstRender) {
      renderedFingerprintRef.current = fingerprint;
      void perform("final", draftRef.current);
      return;
    }

    scheduleDraft();
  }, [
    clearDraftTimers,
    fingerprint,
    perform,
    phase,
    scheduleDraft,
    sessionId,
  ]);

  useEffect(() => {
    return () => {
      controllerRef.current?.abort();
      clearDraftTimers();
      renderedFingerprintRef.current = null;
      inflightRef.current = null;
    };
  }, [clearDraftTimers]);

  const requestFinal = useCallback(async (): Promise<void> => {
    clearDraftTimers();
    const nextFingerprint = fingerprintRef.current;
    renderedFingerprintRef.current = nextFingerprint;
    if (completedFinalFingerprintRef.current === nextFingerprint) {
      return;
    }
    await perform("final", draftRef.current);
  }, [clearDraftTimers, perform]);

  const retry = useCallback(async (): Promise<void> => {
    clearDraftTimers();
    renderedFingerprintRef.current = fingerprintRef.current;
    completedFinalFingerprintRef.current = null;
    await perform("final", draftRef.current);
  }, [clearDraftTimers, perform]);

  const cancel = useCallback(() => {
    clearDraftTimers();
    controllerRef.current?.abort();
    inflightRef.current = null;
  }, [clearDraftTimers]);

  return { preview: state.preview, requestFinal, retry, cancel };
}
