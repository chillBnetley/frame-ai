"use client";

import { useCallback, useEffect, useState } from "react";

export const PREVIEW_OBSERVER_ROOT_MARGIN = "-64px 0px 0px 0px";

export interface UsePreviewVisibilityOptions {
  threshold?: number;
  rootMargin?: string;
}

export interface UsePreviewVisibilityResult {
  sentinelRef: (node: Element | null) => void;
  isVisible: boolean;
}

export function usePreviewVisibility(
  options: UsePreviewVisibilityOptions = {},
): UsePreviewVisibilityResult {
  const { threshold = 0.2, rootMargin = PREVIEW_OBSERVER_ROOT_MARGIN } = options;
  const [target, setTarget] = useState<Element | null>(null);
  const [isVisible, setIsVisible] = useState(true);

  const sentinelRef = useCallback((node: Element | null) => {
    setTarget(node);
  }, []);

  useEffect(() => {
    if (target === null || typeof IntersectionObserver === "undefined") {
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (entry) {
          setIsVisible(entry.isIntersecting);
        }
      },
      { threshold, rootMargin },
    );
    observer.observe(target);

    return () => observer.disconnect();
  }, [rootMargin, target, threshold]);

  return { sentinelRef, isVisible };
}
