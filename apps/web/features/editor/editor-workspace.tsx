"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ErrorAlert } from "@/components/error-alert";
import { CheckCircleIcon, ShieldCheckIcon } from "@/components/icons";
import { HealthIndicator } from "@/features/editor/health-indicator";
import { UploadDropzone } from "@/features/editor/upload-dropzone";
import { UploadResult } from "@/features/editor/upload-result";
import { fetchHealth, uploadImage } from "@/lib/api/client";
import { describeUploadError } from "@/lib/api/errors";
import { validateUploadFile } from "@/lib/upload-validation";
import type { ApiStatus, UploadedImage, UploadError } from "@/types/image";

const NON_RETRYABLE_CODES = new Set(["file_too_large", "unsupported_media_type", "empty_file"]);

function useApiHealth(): ApiStatus {
  const [status, setStatus] = useState<ApiStatus>("checking");

  useEffect(() => {
    let active = true;

    const check = async () => {
      try {
        await fetchHealth();
        if (active) {
          setStatus("online");
        }
      } catch {
        if (active) {
          setStatus("offline");
        }
      }
    };

    void check();
    const interval = globalThis.setInterval(check, 30_000);

    return () => {
      active = false;
      globalThis.clearInterval(interval);
    };
  }, []);

  return status;
}

export function EditorWorkspace() {
  const apiStatus = useApiHealth();
  const [image, setImage] = useState<UploadedImage | null>(null);
  const [error, setError] = useState<UploadError | null>(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const handleFileSelected = useCallback(async (file: File) => {
    const validation = validateUploadFile(file);
    if (!validation.ok) {
      setPendingFile(file);
      setError({ code: validation.code, message: validation.message });
      return;
    }

    setPendingFile(file);
    setError(null);
    setImage(null);
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setUploading(true);

    try {
      const uploaded = await uploadImage(file, controller.signal);
      if (!controller.signal.aborted) {
        setImage(uploaded);
        setPendingFile(null);
      }
    } catch (uploadError) {
      if (!controller.signal.aborted) {
        setError(describeUploadError(uploadError));
      }
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null;
        setUploading(false);
      }
    }
  }, []);

  const canRetry =
    pendingFile !== null && error !== null && !NON_RETRYABLE_CODES.has(error.code);

  return (
    <section aria-labelledby="workspace-heading" className="relative">
      <div className="overflow-hidden rounded-3xl border border-white/10 bg-[#0c0d0f]/90 shadow-[0_30px_80px_-30px_rgba(0,0,0,0.9)] backdrop-blur-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/8 px-4 py-3.5 sm:px-6">
          <div className="flex items-center gap-3">
            <span className="grid size-8 place-items-center rounded-lg border border-white/10 bg-white/[0.03] font-mono text-[10px] text-accent">
              01
            </span>
            <div>
              <h2 id="workspace-heading" className="text-sm font-medium tracking-tight text-white">
                原图工作区
              </h2>
              <p className="mt-0.5 font-mono text-[9px] uppercase tracking-[0.18em] text-white/30">
                Upload · Validate · Store
              </p>
            </div>
          </div>
          <HealthIndicator status={apiStatus} />
        </div>

        <div className="p-3 sm:p-6">
          {error && (
            <ErrorAlert
              error={error}
              onRetry={canRetry && pendingFile ? () => void handleFileSelected(pendingFile) : undefined}
              onDismiss={() => setError(null)}
            />
          )}

          {image ? (
            <UploadResult
              key={image.imageId}
              image={image}
              uploading={uploading}
              onFileSelected={handleFileSelected}
            />
          ) : (
            <UploadDropzone onFileSelected={handleFileSelected} disabled={uploading} />
          )}

          <p className="sr-only" role="status" aria-live="polite">
            {uploading ? "正在上传照片" : image ? "照片上传完成" : ""}
          </p>
        </div>

        <div className="flex flex-col gap-2 border-t border-white/8 bg-black/15 px-4 py-3 text-[11px] text-white/35 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <span className="inline-flex items-center gap-2">
            <ShieldCheckIcon className="size-3.5 text-accent/70" />
            原图只读保存；预览直接读取服务端原始字节。
          </span>
          <span className="inline-flex items-center gap-2">
            <CheckCircleIcon className="size-3.5 text-white/25" />
            阶段 1 不上传第三方存储，不调用 AI 模型。
          </span>
        </div>
      </div>
    </section>
  );
}
