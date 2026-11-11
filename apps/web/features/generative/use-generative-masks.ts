"use client";

import { useCallback, useEffect, useState } from "react";

import { listGenerativeMasks } from "@/lib/api/generative";
import type { GenerativeMaskView } from "@/types/generative";

export interface GenerativeMasksController {
  masks: GenerativeMaskView[];
  selectedMaskId: string | null;
  selectMask: (maskId: string) => void;
  addMask: (mask: GenerativeMaskView) => void;
  reload: () => void;
}

/** Lists the session masks once and keeps a selection that new masks adopt. */
export function useGenerativeMasks(
  sessionId: string,
  initialMaskId: string | null = null,
): GenerativeMasksController {
  const [masks, setMasks] = useState<GenerativeMaskView[]>([]);
  const [selectedMaskId, setSelectedMaskId] = useState<string | null>(initialMaskId);
  const [reloadNonce, setReloadNonce] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    listGenerativeMasks(sessionId, { limit: 20 }, controller.signal)
      .then((response) => {
        if (controller.signal.aborted) {
          return;
        }
        setMasks(response.items);
        if (response.items.length > 0 && !initialMaskId) {
          setSelectedMaskId((prev) => prev || response.items[0].maskId);
        }
      })
      .catch(() => {
        // An empty mask list is a valid state: the user can still draw one.
      });
    return () => controller.abort();
  }, [sessionId, initialMaskId, reloadNonce]);

  const selectMask = useCallback((maskId: string) => {
    setSelectedMaskId(maskId);
  }, []);

  const addMask = useCallback((mask: GenerativeMaskView) => {
    setMasks((prev) => [mask, ...prev]);
    setSelectedMaskId(mask.maskId);
  }, []);

  const reload = useCallback(() => setReloadNonce((value) => value + 1), []);

  return { masks, selectedMaskId, selectMask, addMask, reload };
}
