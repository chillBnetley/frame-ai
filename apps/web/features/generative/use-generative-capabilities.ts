"use client";

import { useEffect, useState } from "react";

import { getGenerativeCapabilities } from "@/lib/api/generative";
import type { GenerativeCapabilitiesResponse } from "@/types/generative";

/** Provider capabilities, or null while offline. Hints degrade silently. */
export function useGenerativeCapabilities(): GenerativeCapabilitiesResponse | null {
  const [capabilities, setCapabilities] = useState<GenerativeCapabilitiesResponse | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getGenerativeCapabilities(controller.signal)
      .then(setCapabilities)
      .catch(() => {
        // Capabilities only annotate the form; the backend still validates.
      });
    return () => controller.abort();
  }, []);

  return capabilities;
}
