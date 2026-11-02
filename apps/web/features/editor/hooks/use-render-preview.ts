"use client";

import { useCallback, useEffect, useRef } from "react";

import { useEditorDispatch, useEditorState } from "@/features/editor/state/editor-context";
import type { PreviewState } from "@/features/editor/state/editor-reducer";
import { renderPreview } from "@/lib/api/sessions";
import { describeEditorError, isSilentEditorError } from "@/lib/error-messages";
import { recipeFingerprint } from "@/lib/recipe";
import type { EditRecipe } from "@/types/session";

export const PREVIEW_DEBOUNCE_MS = 120;

export interface UseRenderPreviewOptions {
  debounceMs?: number;
}

export interface UseRenderPreviewResult {
  preview: PreviewState;
  requestFinal: () => Promise<void>;
  retry: () => Promise<void>;
  cancel: () => void;
}

export function useRenderPreview(
  options: UseRenderPreviewOptions = {},
): UseRenderPreviewResult {
  const { debounceMs = PREVIEW_DEBOUNCE_MS } = options;
  const state = useEditorState();
  const dispatch = useEditorDispatch();
  const { sessionId, draft, phase } = state;
  const ready = phase === "ready";

  const seqRef = useRef(0);
  const controllerRef = useRef<AbortController | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const renderedFingerprintRef = useRef<string | null>(null);
  const renderedSessionRef = useRef<string | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const perform = useCallback(
    async (quality: "draft" | "final", recipe: EditRecipe = draft): Promise<void> => {
      if (!ready || sessionId === null) {
        return;
      }

      const seq = seqRef.current + 1;
      seqRef.current = seq;
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      dispatch({ type: "preview-loading", seq });

      try {
        const result = await renderPreview(
          sessionId,
          { recipe, quality },
          controller.signal,
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
        });
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
      }
    },
    [dispatch, draft, ready, sessionId],
  );

  const fingerprint = recipeFingerprint(draft);

  useEffect(() => {
    if (renderedSessionRef.current !== sessionId) {
      renderedSessionRef.current = sessionId;
      renderedFingerprintRef.current = null;
      controllerRef.current?.abort();
      clearTimer();
    }
    if (!sessionId || phase !== "ready") {
      return;
    }
    if (renderedFingerprintRef.current === fingerprint) {
      return;
    }

    const isFirstRender = renderedFingerprintRef.current === null;
    renderedFingerprintRef.current = fingerprint;
    clearTimer();

    if (isFirstRender) {
      void perform("final");
      return;
    }

    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      void perform("draft");
    }, debounceMs);

    return clearTimer;
  }, [clearTimer, debounceMs, fingerprint, perform, phase, sessionId]);

  useEffect(() => {
    return () => {
      controllerRef.current?.abort();
      clearTimer();
      renderedFingerprintRef.current = null;
    };
  }, [clearTimer]);

  const requestFinal = useCallback(async (): Promise<void> => {
    clearTimer();
    renderedFingerprintRef.current = recipeFingerprint(draft);
    await perform("final", draft);
  }, [clearTimer, draft, perform]);

  const retry = useCallback(async (): Promise<void> => {
    clearTimer();
    await perform("final", draft);
  }, [clearTimer, draft, perform]);

  const cancel = useCallback(() => {
    clearTimer();
    controllerRef.current?.abort();
  }, [clearTimer]);

  return { preview: state.preview, requestFinal, retry, cancel };
}
