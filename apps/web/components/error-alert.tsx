"use client";

import { AlertTriangleIcon } from "@/components/icons";
import type { UploadError } from "@/types/image";

interface ErrorAlertProps {
  error: UploadError;
  stage?: string;
  retryLabel?: string;
  requestId?: string | null;
  onRetry?: () => void;
  onDismiss?: () => void;
}

export function ErrorAlert({
  error,
  stage,
  retryLabel = "重试上传",
  requestId,
  onRetry,
  onDismiss,
}: ErrorAlertProps) {
  const resolvedRequestId = requestId ?? error.requestId ?? null;

  return (
    <div
      role="alert"
      className="mb-4 flex flex-col gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between"
    >
      <div className="flex items-start gap-3">
        <AlertTriangleIcon className="mt-0.5 size-5 shrink-0 text-red-500" />
        <div>
          <p className="text-sm font-medium text-red-800">{error.message}</p>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 font-mono text-[10px] tracking-[0.06em] text-red-700/75">
            {stage && <span>{stage}</span>}
            <span className="uppercase">{error.code}</span>
            {resolvedRequestId && (
              <span className="break-all normal-case" title={resolvedRequestId}>
                请求 ID {resolvedRequestId}
              </span>
            )}
          </p>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2 pl-8 sm:pl-0">
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="min-h-11 rounded-lg border border-red-200 bg-white px-3 py-1.5 text-xs font-medium text-red-700 transition-colors hover:bg-red-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-500"
          >
            {retryLabel}
          </button>
        )}
        {onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg px-2.5 py-1.5 text-xs text-red-600 transition-colors hover:text-red-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-500"
            aria-label="关闭错误提示"
          >
            关闭
          </button>
        )}
      </div>
    </div>
  );
}
