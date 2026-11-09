"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiClientError } from "@/lib/api/client";
import { fetchImageLibrary } from "@/lib/api/personal-style";
import type { ImageListItem } from "@/types/personal-style";

export interface ImageLibraryState {
  images: ImageListItem[];
  nextOffset: number | null;
  loading: boolean;
  loadingMore: boolean;
  error: string | null;
  reload: () => void;
  loadMore: () => void;
}

export function useImageLibrary(limit = 60): ImageLibraryState {
  const [images, setImages] = useState<ImageListItem[]>([]);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    fetchImageLibrary({ limit }, controller.signal)
      .then((response) => {
        if (!controller.signal.aborted) {
          setImages(response.images);
          setNextOffset(response.nextOffset ?? null);
          setLoading(false);
        }
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(
            reason instanceof ApiClientError
              ? reason.message
              : "无法加载图片库，请确认 API 服务已经启动。",
          );
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [attempt, limit]);

  const reload = useCallback(() => {
    setLoading(true);
    setError(null);
    setAttempt((value) => value + 1);
  }, []);

  const loadMore = useCallback(() => {
    if (nextOffset === null || loadingMore || loading) return;
    setLoadingMore(true);
    fetchImageLibrary({ limit, offset: nextOffset })
      .then((response) => {
        setImages((current) => [...current, ...response.images]);
        setNextOffset(response.nextOffset ?? null);
      })
      .catch((reason: unknown) => {
        setError(
          reason instanceof ApiClientError ? reason.message : "加载更多图片失败。",
        );
      })
      .finally(() => setLoadingMore(false));
  }, [limit, loading, loadingMore, nextOffset]);

  return {
    images,
    nextOffset,
    loading,
    loadingMore,
    error,
    reload,
    loadMore,
  };
}
