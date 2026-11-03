"use client";

import { useCallback, useEffect, useRef } from "react";

import { useEditorDispatch, useEditorState } from "@/features/editor/state/editor-context";
import { ApiClientError } from "@/lib/api/client";
import {
  activateRevision,
  createIdempotencyKey,
  createRevision,
  createSession,
  getSession,
  listRevisions,
  redoSession,
  resetSession,
  undoSession,
} from "@/lib/api/sessions";
import { describeEditorError } from "@/lib/error-messages";
import { normalizeRecipe, recipeFingerprint } from "@/lib/recipe";
import type { SessionState } from "@/types/session";

const NON_RETRYABLE_SAVE_CODES = new Set([
  "validation_error",
  "session_not_found",
  "revision_not_found",
  "idempotency_key_reuse",
]);

const SESSION_QUERY_KEY = "session";

export function readSessionIdFromUrl(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return new URLSearchParams(window.location.search).get(SESSION_QUERY_KEY);
}

export function syncSessionUrl(sessionId: string): void {
  if (typeof window === "undefined") {
    return;
  }
  const url = new URL(window.location.href);
  url.searchParams.set(SESSION_QUERY_KEY, sessionId);
  window.history.replaceState(window.history.state, "", url);
}

export function clearSessionUrl(): void {
  if (typeof window === "undefined") {
    return;
  }
  const url = new URL(window.location.href);
  url.searchParams.delete(SESSION_QUERY_KEY);
  window.history.replaceState(window.history.state, "", url);
}

export function useSessionRestore(): void {
  const dispatch = useEditorDispatch();

  useEffect(() => {
    const sessionId = readSessionIdFromUrl();
    if (!sessionId) {
      return;
    }

    const controller = new AbortController();
    let cancelled = false;
    dispatch({ type: "session-loading" });

    void getSession(sessionId, controller.signal)
      .then((session) => {
        if (cancelled) {
          return;
        }
        dispatch({ type: "session-ready", state: session });
        void listRevisions(session.sessionId, { limit: 50 }, controller.signal)
          .then((response) => {
            if (!cancelled) {
              dispatch({
                type: "history-loaded",
                items: response.items,
                nextCursor:
                  response.nextCursor === null || response.nextCursor === undefined
                    ? null
                    : Number(response.nextCursor),
              });
            }
          })
          .catch(() => {
            // History is a secondary view; a failed fetch must not drop the session.
          });
      })
      .catch((error: unknown) => {
        if (cancelled) {
          return;
        }
        if (
          error instanceof ApiClientError &&
          (error.code === "session_not_found" || error.status === 404)
        ) {
          clearSessionUrl();
        }
        dispatch({ type: "session-load-failed", error: describeEditorError(error) });
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [dispatch]);
}

async function applyConflictState(
  sessionId: string,
  dispatch: ReturnType<typeof useEditorDispatch>,
): Promise<void> {
  try {
    const fresh = await getSession(sessionId);
    dispatch({ type: "conflict", state: fresh });
  } catch (error) {
    dispatch({ type: "error", error: describeEditorError(error) });
  }
}

export interface SessionActions {
  startSession: (imageId: string) => Promise<boolean>;
  commit: () => Promise<boolean>;
  undo: () => Promise<boolean>;
  redo: () => Promise<boolean>;
  reset: () => Promise<boolean>;
  activate: (revisionId: string) => Promise<boolean>;
  refresh: () => Promise<boolean>;
}

export function useSessionActions(): SessionActions {
  const { sessionId, phase, draft, committed, activeRevisionId, save } =
    useEditorState();
  const dispatch = useEditorDispatch();

  const sessionIdRef = useRef(sessionId);
  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  const loadHistory = useCallback(
    async (targetSessionId: string): Promise<void> => {
      try {
        const response = await listRevisions(targetSessionId, { limit: 50 });
        if (sessionIdRef.current !== targetSessionId) {
          return;
        }
        dispatch({
          type: "history-loaded",
          items: response.items,
          nextCursor:
            response.nextCursor === null || response.nextCursor === undefined
              ? null
              : Number(response.nextCursor),
        });
      } catch {
        // History is best-effort; the session itself stays usable.
      }
    },
    [dispatch],
  );

  const startSession = useCallback(
    async (imageId: string): Promise<boolean> => {
      dispatch({ type: "session-loading" });
      try {
        const session = await createSession(imageId);
        syncSessionUrl(session.sessionId);
        dispatch({ type: "session-ready", state: session });
        void loadHistory(session.sessionId);
        return true;
      } catch (error) {
        dispatch({ type: "session-load-failed", error: describeEditorError(error) });
        return false;
      }
    },
    [dispatch, loadHistory],
  );

  const saveDraft = useCallback(async (): Promise<{
    ok: boolean;
    state: SessionState | null;
  }> => {
    if (
      phase !== "ready" ||
      sessionId === null ||
      activeRevisionId === null ||
      save.status === "saving"
    ) {
      return { ok: false, state: null };
    }

    const recipe = normalizeRecipe(draft);
    const fingerprint = recipeFingerprint(recipe);
    if (fingerprint === recipeFingerprint(committed)) {
      return { ok: true, state: null };
    }

    const reusableKey =
      save.idempotencyFingerprint === fingerprint ? save.idempotencyKey : null;
    const idempotencyKey = reusableKey ?? createIdempotencyKey();

    dispatch({ type: "save-start", idempotencyKey, fingerprint });

    try {
      const result = await createRevision(
        sessionId,
        {
          recipe,
          parentRevisionId: activeRevisionId,
          source: "user",
        },
        idempotencyKey,
      );
      dispatch({ type: "save-success", state: result.state });
      void loadHistory(sessionId);
      return { ok: true, state: result.state };
    } catch (error) {
      const normalized = describeEditorError(error);
      if (error instanceof ApiClientError && error.code === "revision_conflict") {
        await applyConflictState(sessionId, dispatch);
        void loadHistory(sessionId);
        return { ok: false, state: null };
      }
      const retryable =
        !(error instanceof ApiClientError) || !NON_RETRYABLE_SAVE_CODES.has(error.code);
      dispatch({ type: "save-failure", error: normalized, retryable });
      return { ok: false, state: null };
    }
  }, [
    activeRevisionId,
    committed,
    dispatch,
    draft,
    loadHistory,
    phase,
    save.idempotencyFingerprint,
    save.idempotencyKey,
    save.status,
    sessionId,
  ]);

  const commit = useCallback(
    async (): Promise<boolean> => (await saveDraft()).ok,
    [saveDraft],
  );

  const runHistoryAction = useCallback(
    async (
      operation: (
        targetSessionId: string,
        expectedRevisionId: string | null,
      ) => Promise<SessionState>,
    ): Promise<boolean> => {
      if (phase !== "ready" || sessionId === null || save.status === "saving") {
        return false;
      }

      let expectedRevisionId = activeRevisionId;
      const dirty = recipeFingerprint(draft) !== recipeFingerprint(committed);
      if (dirty) {
        const saved = await saveDraft();
        if (!saved.ok) {
          return false;
        }
        if (saved.state !== null) {
          expectedRevisionId = saved.state.activeRevisionId;
        }
      }

      try {
        const next = await operation(sessionId, expectedRevisionId);
        dispatch({ type: "session-replaced", state: next });
        void loadHistory(sessionId);
        return true;
      } catch (error) {
        if (error instanceof ApiClientError && error.code === "revision_conflict") {
          await applyConflictState(sessionId, dispatch);
        } else {
          dispatch({ type: "error", error: describeEditorError(error) });
        }
        return false;
      }
    },
    [
      activeRevisionId,
      committed,
      dispatch,
      draft,
      loadHistory,
      phase,
      save.status,
      saveDraft,
      sessionId,
    ],
  );

  const undo = useCallback(
    () =>
      runHistoryAction((targetSessionId, expectedRevisionId) =>
        undoSession(targetSessionId, expectedRevisionId),
      ),
    [runHistoryAction],
  );

  const redo = useCallback(
    () => runHistoryAction((targetSessionId) => redoSession(targetSessionId)),
    [runHistoryAction],
  );

  const reset = useCallback(
    () => runHistoryAction((targetSessionId) => resetSession(targetSessionId)),
    [runHistoryAction],
  );

  const activate = useCallback(
    (revisionId: string) =>
      runHistoryAction((targetSessionId) => activateRevision(targetSessionId, revisionId)),
    [runHistoryAction],
  );

  const refresh = useCallback(async (): Promise<boolean> => {
    if (sessionId === null) {
      return false;
    }
    try {
      const fresh = await getSession(sessionId);
      dispatch({ type: "conflict", state: fresh });
      void loadHistory(sessionId);
      return true;
    } catch (error) {
      dispatch({ type: "error", error: describeEditorError(error) });
      return false;
    }
  }, [dispatch, loadHistory, sessionId]);

  return { startSession, commit, undo, redo, reset, activate, refresh };
}
