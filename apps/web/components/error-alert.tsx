"use client";

import { AlertTriangleIcon } from "@/components/icons";
import type { UploadError } from "@/types/image";

interface ErrorAlertProps {
  error: UploadError;
  onRetry?: () => void;
  onDismiss?: () => void;
}

export function ErrorAlert({ error, onRetry, onDismiss }: ErrorAlertProps) {
  return (
    <div
      role="alert"
      className="mb-4 flex flex-col gap-3 rounded-xl border border-red-400/25 bg-red-400/[0.07] px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between"
    >
      <div className="flex items-start gap-3">
        <AlertTriangleIcon className="mt-0.5 size-5 shrink-0 text-red-300" />
        <div>
          <p className="text-sm font-medium text-red-100">{error.message}</p>
          <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.12em] text-red-200/45">
            {error.code}
          </p>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2 pl-8 sm:pl-0">
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="min-h-11 rounded-lg border border-red-300/25 bg-red-300/10 px-3 py-1.5 text-xs font-medium text-red-100 transition-colors hover:bg-red-300/20 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-200"
          >
            重试上传
          </button>
        )}
        {onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg px-2.5 py-1.5 text-xs text-red-100/60 transition-colors hover:text-red-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-200"
            aria-label="关闭错误提示"
          >
            关闭
          </button>
        )}
      </div>
    </div>
  );
}
