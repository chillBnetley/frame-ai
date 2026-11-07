"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { describeEditorError, type EditorError } from "@/lib/error-messages";
import {
  deleteFeedback as deleteFeedbackRequest,
  fetchFeedback,
  recordFeedback,
} from "@/lib/api/photographer";
import type {
  FeedbackAction,
  FeedbackRubric,
  FeedbackSource,
  FeedbackSummary,
  PhotographerFeedback,
} from "@/types/photographer";

/**
 * What the user just did. "modified" is never sent: the server derives it by
 * comparing the stored recipe with the plan it came from.
 */
export interface FeedbackDecision {
  action: Exclude<FeedbackAction, "modified">;
  source: FeedbackSource | null;
  planId: string | null;
  revisionId: string | null;
  rubric?: FeedbackRubric | null;
}

export interface UseFeedbackResult {
  sessionId: string | null;
  items: PhotographerFeedback[];
  summary: FeedbackSummary | null;
  loading: boolean;
  historyError: EditorError | null;
  /** Decisions the server has not confirmed; they retry without blocking editing. */
  unsent: number;
  sendError: EditorError | null;
  /** Non-null while the optional rating dialog is waiting for an answer. */
  rating: FeedbackDecision | null;
  /** Resolves true when the server confirmed every queued decision. */
  record: (decision: FeedbackDecision) => Promise<boolean>;
  recordAndAskForRating: (decision: FeedbackDecision) => Promise<boolean>;
  submitRating: (rubric: FeedbackRubric) => Promise<boolean>;
  dismissRating: () => void;
  retryUnsent: () => Promise<boolean>;
  refresh: () => Promise<void>;
  remove: (feedbackId: string) => Promise<void>;
}

function decisionKey(decision: FeedbackDecision): string {
  return `${decision.action}|${decision.source ?? "-"}|${decision.planId ?? "-"}|${decision.revisionId ?? "-"}`;
}

function withSession(
  sessionId: string,
  decision: FeedbackDecision,
): Parameters<typeof recordFeedback>[0] {
  return {
    sessionId,
    action: decision.action,
    ...(decision.source === null ? {} : { source: decision.source }),
    ...(decision.planId === null ? {} : { planId: decision.planId }),
    ...(decision.revisionId === null ? {} : { revisionId: decision.revisionId }),
    ...(decision.rubric ? { rubric: decision.rubric } : {}),
  };
}

export function useFeedback(sessionId: string | null): UseFeedbackResult {
  const [items, setItems] = useState<PhotographerFeedback[]>([]);
  const [summary, setSummary] = useState<FeedbackSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [historyError, setHistoryError] = useState<EditorError | null>(null);
  const [queued, setQueued] = useState<{ owner: string | null; count: number }>(
    { owner: null, count: 0 },
  );
  const [sendError, setSendError] = useState<EditorError | null>(null);
  const [rating, setRating] = useState<FeedbackDecision | null>(null);

  /** Latest decision per key: a rating replaces the accept it annotates. */
  const queueRef = useRef(new Map<string, FeedbackDecision>());
  const queueOwnerRef = useRef<string | null>(null);
  const flushingRef = useRef(false);
  const controllerRef = useRef<AbortController | null>(null);
  /** The session the cached results belong to; results of any other session are hidden. */
  const [owner, setOwner] = useState<string | null>(null);

  // A session switch, like an unmount, abandons whatever request is still open.
  useEffect(
    () => () => {
      controllerRef.current?.abort();
    },
    [sessionId],
  );

  const fresh = owner === sessionId;

  const refresh = useCallback(async (): Promise<void> => {
    if (sessionId === null) {
      return;
    }
    const controller = new AbortController();
    controllerRef.current?.abort();
    controllerRef.current = controller;
    setOwner(sessionId);
    setLoading(true);
    setHistoryError(null);
    try {
      const response = await fetchFeedback({ sessionId }, controller.signal);
      if (controller.signal.aborted) {
        return;
      }
      setItems(response.items);
      setSummary(response.summary);
    } catch (error) {
      if (controller.signal.aborted) {
        return;
      }
      setHistoryError(describeEditorError(error));
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false);
      }
    }
  }, [sessionId]);

  const send = useCallback(
    async (decision: FeedbackDecision): Promise<boolean> => {
      if (sessionId === null) {
        return false;
      }
      // This hook instance now answers for this session, results or errors.
      setOwner(sessionId);
      try {
        await recordFeedback(withSession(sessionId, decision));
        return true;
      } catch (error) {
        if (error instanceof Error && error.name === "AbortError") {
          return false;
        }
        setSendError(describeEditorError(error));
        return false;
      }
    },
    [sessionId],
  );

  const flush = useCallback(async (): Promise<boolean> => {
    if (flushingRef.current) {
      return queueRef.current.size === 0;
    }
    flushingRef.current = true;
    try {
      const pending = [...queueRef.current.entries()];
      for (const [key, decision] of pending) {
        if (!(await send(decision))) {
          break;
        }
        // Only drop what the server confirmed and nobody re-queued meanwhile.
        if (queueRef.current.get(key) === decision) {
          queueRef.current.delete(key);
        }
      }
      setQueued((current) => ({ ...current, count: queueRef.current.size }));
      if (queueRef.current.size === 0) {
        setSendError(null);
      }
      return queueRef.current.size === 0;
    } finally {
      flushingRef.current = false;
    }
  }, [send]);

  const record = useCallback(
    async (decision: FeedbackDecision): Promise<boolean> => {
      if (sessionId === null) {
        return false;
      }
      // A decision belongs to the session it was made in; a new image starts clean.
      if (queueOwnerRef.current !== sessionId) {
        queueRef.current.clear();
        queueOwnerRef.current = sessionId;
      }
      queueRef.current.set(decisionKey(decision), decision);
      setQueued({ owner: sessionId, count: queueRef.current.size });
      const stored = await flush();
      if (stored) {
        await refresh();
      }
      return stored;
    },
    [flush, refresh, sessionId],
  );

  const recordAndAskForRating = useCallback(
    async (decision: FeedbackDecision): Promise<boolean> => {
      if (!(await record(decision))) {
        // Nothing stored yet: asking for a score would only create a duplicate.
        return false;
      }
      setRating(decision);
      return true;
    },
    [record],
  );

  const submitRating = useCallback(
    async (rubric: FeedbackRubric): Promise<boolean> => {
      if (rating === null) {
        return false;
      }
      const stored = await record({ ...rating, rubric });
      if (stored) {
        setRating(null);
      }
      return stored;
    },
    [rating, record],
  );

  const dismissRating = useCallback(() => {
    setRating(null);
  }, []);

  const retryUnsent = useCallback(async (): Promise<boolean> => {
    const stored = await flush();
    if (stored) {
      await refresh();
    }
    return stored;
  }, [flush, refresh]);

  const remove = useCallback(
    async (feedbackId: string): Promise<void> => {
      const previous = items;
      setItems((current) => current.filter((item) => item.id !== feedbackId));
      try {
        await deleteFeedbackRequest(feedbackId);
      } catch (error) {
        setItems(previous);
        setHistoryError(describeEditorError(error));
        return;
      }
      await refresh();
    },
    [items, refresh],
  );

  return {
    sessionId,
    items: fresh ? items : [],
    summary: fresh ? summary : null,
    loading: fresh ? loading : false,
    historyError: fresh ? historyError : null,
    unsent: queued.owner === sessionId ? queued.count : 0,
    sendError: fresh ? sendError : null,
    rating: fresh ? rating : null,
    record,
    recordAndAskForRating,
    submitRating,
    dismissRating,
    retryUnsent,
    refresh,
    remove,
  };
}
