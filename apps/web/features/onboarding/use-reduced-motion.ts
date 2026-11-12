"use client";

import { useEffect, useState } from "react";

/**
 * Reads the OS-level reduced-motion preference. CSS already shortens animations;
 * JavaScript timers must opt out separately or the splash would still advance
 * while the user sees a static page.
 */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(query.matches);

    update();
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);

  return reduced;
}
