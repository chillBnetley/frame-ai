"use client";

import { useEffect, useState } from "react";

import { listPersonalStyles } from "@/lib/api/personal-style";
import type { PersonalStyleItem } from "@/types/personal-style";
import { selectablePersonalStyles } from "./style-instruction";

/** Published Visual DNA styles, or an empty list while offline. The hint degrades silently. */
export function usePersonalStyleOptions(): PersonalStyleItem[] {
  const [styles, setStyles] = useState<PersonalStyleItem[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    listPersonalStyles({ status: "published" }, controller.signal)
      .then((response) => {
        if (!controller.signal.aborted) {
          setStyles(selectablePersonalStyles(response.styles));
        }
      })
      .catch(() => {
        // Style presets are optional; local generation still works without them.
      });
    return () => controller.abort();
  }, []);

  return styles;
}