"use client";

import { useCallback, useEffect, useState } from "react";

import { getGenerativeStorage } from "@/lib/api/generative";
import type { GenerativeStorageResponse } from "@/types/generative";

export interface GenerativeStorageState {
  storage: GenerativeStorageResponse | null;
  reload: () => void;
}

/** Local generative disk budget and usage, or null while offline. */
export function useGenerativeStorage(): GenerativeStorageState {
  const [storage, setStorage] = useState<GenerativeStorageResponse | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    getGenerativeStorage(controller.signal)
      .then(setStorage)
      .catch(() => {
        // Storage usage is informational; backend enforces the budget.
      });
    return () => controller.abort();
  }, [nonce]);

  const reload = useCallback(() => {
    setNonce((current) => current + 1);
  }, []);

  return { storage, reload };
}
