"use client";

import { useCallback, useEffect, useState } from "react";

import { fetchStyles } from "@/lib/api/photographer";
import { describeEditorError, type EditorError } from "@/lib/error-messages";
import type { PhotographerStyle } from "@/types/photographer";

export interface UseStylesResult {
  styles: readonly PhotographerStyle[];
  loading: boolean;
  error: EditorError | null;
  reload: () => void;
}

/**
 * `styles` stays null until the first response lands, which is what makes
 * `loading` derivable instead of another state flag set inside the effect.
 */
export function useStyles(enabled: boolean = true): UseStylesResult {
  const [styles, setStyles] = useState<readonly PhotographerStyle[] | null>(
    null,
  );
  const [error, setError] = useState<EditorError | null>(null);
  const [attempt, setAttempt] = useState(0);

  const reload = useCallback(() => {
    setStyles(null);
    setError(null);
    setAttempt((value) => value + 1);
  }, []);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    const controller = new AbortController();
    let active = true;

    fetchStyles(controller.signal)
      .then((response) => {
        if (active) {
          setStyles(response.styles);
          setError(null);
        }
      })
      .catch((caught: unknown) => {
        if (!active || controller.signal.aborted) {
          return;
        }
        setStyles([]);
        setError(describeEditorError(caught));
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [attempt, enabled]);

  return {
    styles: styles ?? [],
    loading: enabled && styles === null,
    error,
    reload,
  };
}
