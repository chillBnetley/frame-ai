"use client";

import { useEffect, useRef, useState, type Ref, type SyntheticEvent } from "react";

import { ImageIcon } from "@/components/icons";
import type { PreviewState } from "@/features/editor/state/editor-reducer";

export interface PreviewImageProps {
  preview: PreviewState;
  alt: string;
  errorMessage?: string | null;
  onError?: () => void;
  containerRef?: Ref<HTMLDivElement>;
  id?: string;
  className?: string;
  imageClassName?: string;
  showPlaceholder?: boolean;
}

interface FailedPreview {
  url: string;
  seq: number;
}

export function PreviewImage({
  preview,
  alt,
  errorMessage,
  onError,
  containerRef,
  id,
  className,
  imageClassName,
  showPlaceholder = true,
}: PreviewImageProps) {
  const [displayedUrl, setDisplayedUrl] = useState<string | null>(preview.url);
  const [failed, setFailed] = useState<FailedPreview | null>(null);
  const targetUrlRef = useRef<string | null>(preview.url);
  const onErrorRef = useRef(onError);
  const notifiedFailureRef = useRef<string | null>(null);

  useEffect(() => {
    targetUrlRef.current = preview.url;
  }, [preview.url]);

  useEffect(() => {
    onErrorRef.current = onError;
  }, [onError]);

  const failedCurrent =
    failed !== null && failed.url === preview.url && failed.seq === preview.seq;
  const firstUrl =
    displayedUrl === null && preview.url !== null && !failedCurrent
      ? preview.url
      : null;
  const activeUrl = preview.url === null ? null : (displayedUrl ?? firstUrl);
  const pendingUrl =
    preview.url !== null &&
    displayedUrl !== null &&
    preview.url !== displayedUrl &&
    !failedCurrent
      ? preview.url
      : null;
  const updating = preview.status === "loading" || pendingUrl !== null;
  const showStaleNotice =
    failed !== null &&
    failed.seq === preview.seq &&
    pendingUrl === null &&
    activeUrl !== null &&
    showPlaceholder;

  const notifyFailure = (url: string) => {
    if (notifiedFailureRef.current === url) {
      return;
    }
    notifiedFailureRef.current = url;
    onErrorRef.current?.();
  };

  const handleStagingFailure = (url: string) => {
    if (targetUrlRef.current !== url) {
      return;
    }
    setFailed({ url, seq: preview.seq });
    if (displayedUrl === null) {
      notifyFailure(url);
    }
  };

  const handleStagingLoad = (
    url: string,
    event: SyntheticEvent<HTMLImageElement>,
  ) => {
    const commit = () => {
      if (targetUrlRef.current !== url) {
        return;
      }
      notifiedFailureRef.current = null;
      setDisplayedUrl(url);
      setFailed(null);
    };
    const image = event.currentTarget;
    if (typeof image.decode !== "function") {
      commit();
      return;
    }
    image.decode().then(commit, () => handleStagingFailure(url));
  };

  return (
    <div ref={containerRef} id={id} className={className}>
      {updating && (
        <div className="pointer-events-none absolute inset-x-0 top-0 h-0.5 overflow-hidden bg-white/5">
          <div className="h-full w-1/3 animate-pulse bg-accent/70" />
        </div>
      )}
      {activeUrl ? (
        // eslint-disable-next-line @next/next/no-img-element -- previews are content-addressed JPEGs served by the API
        <img
          src={activeUrl}
          alt={alt}
          className={imageClassName}
          onLoad={
            firstUrl !== null
              ? () => {
                  if (targetUrlRef.current !== firstUrl) {
                    return;
                  }
                  notifiedFailureRef.current = null;
                  setDisplayedUrl(firstUrl);
                }
              : undefined
          }
          onError={() => {
            setDisplayedUrl(null);
            setFailed({ url: activeUrl, seq: preview.seq });
            notifyFailure(activeUrl);
          }}
        />
      ) : showPlaceholder ? (
        <p className="flex items-center gap-2 text-xs text-white/45">
          <ImageIcon className="size-4" />
          {errorMessage
            ? "预览暂时不可用。"
            : pendingUrl
              ? "正在加载预览…"
              : "正在生成预览…"}
        </p>
      ) : null}
      {pendingUrl && (
        // eslint-disable-next-line @next/next/no-img-element -- hidden staging image preloads before the visible layer swaps
        <img
          key={pendingUrl}
          src={pendingUrl}
          alt=""
          aria-hidden="true"
          className="hidden"
          onLoad={(event) => handleStagingLoad(pendingUrl, event)}
          onError={() => handleStagingFailure(pendingUrl)}
        />
      )}
      {showStaleNotice && (
        <span
          role="status"
          className="pointer-events-none absolute bottom-2 left-2 rounded-md bg-white/90 px-2 py-1 text-[10px] text-red-700 shadow-sm"
        >
          新预览加载失败，仍显示上一版本
        </span>
      )}
    </div>
  );
}
