"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ErrorAlert } from "@/components/error-alert";
import { CheckCircleIcon, ImageIcon, ShieldCheckIcon } from "@/components/icons";
import { HealthIndicator } from "@/features/editor/health-indicator";
import { useRenderPreview } from "@/features/editor/hooks/use-render-preview";
import {
  useSessionActions,
  useSessionRestore,
} from "@/features/editor/hooks/use-session";
import { UploadDropzone } from "@/features/editor/upload-dropzone";
import { UploadResult } from "@/features/editor/upload-result";
import {
  EditorProvider,
  useEditorDispatch,
  useEditorState,
} from "@/features/editor/state/editor-context";
import { fetchConfig, fetchHealth, uploadImage } from "@/lib/api/client";
import { describeUploadError } from "@/lib/api/errors";
import { validateUploadFile, type UploadLimits } from "@/lib/upload-validation";
import type { ApiStatus, UploadedImage, UploadError } from "@/types/image";

const NON_RETRYABLE_CODES = new Set([
  "file_too_large",
  "payload_too_large",
  "image_too_many_pixels",
  "unsupported_media_type",
  "animated_not_supported",
  "mime_mismatch",
  "invalid_image",
  "empty_file",
]);

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

function useRuntimeLimits(): UploadLimits | null {
  const [limits, setLimits] = useState<UploadLimits | null>(null);

  useEffect(() => {
    let active = true;

    fetchConfig()
      .then((config) => {
        if (active) {
          setLimits({
            maxUploadBytes: config.maxUploadBytes,
            allowedMimeTypes: config.allowedMimeTypes,
          });
        }
      })
      .catch(() => {
        // The env fallback keeps the UI usable while the API is unreachable.
      });

    return () => {
      active = false;
    };
  }, []);

  return limits;
}

function SessionPreviewPanel() {
  const state = useEditorState();
  const dispatch = useEditorDispatch();
  const { preview, retry } = useRenderPreview();

  if (state.phase === "creatingSession") {
    return (
      <p className="mt-4 rounded-xl border border-white/8 bg-white/[0.02] px-4 py-3 text-xs text-white/45">
        正在准备编辑会话…
      </p>
    );
  }

  if (state.sessionId === null) {
    return null;
  }

  return (
    <section aria-labelledby="first-render-heading" className="mt-4 rounded-2xl border border-white/8 bg-black/20 p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 id="first-render-heading" className="text-sm font-medium text-white">
            服务端首帧渲染
          </h3>
          <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.14em] text-white/30">
            Session {state.sessionId.slice(0, 8)} · Revision{" "}
            {state.activeRevisionId?.slice(0, 8) ?? "—"}
          </p>
        </div>
        <span className="rounded-full border border-white/10 px-2.5 py-1 font-mono text-[10px] text-white/45">
          {preview.quality === "draft" ? "草稿预览" : "终稿预览"}
        </span>
      </div>

      {state.notice && (
        <p
          role="status"
          className="mt-3 rounded-lg border border-amber-300/25 bg-amber-300/10 px-3 py-2 text-xs text-amber-100"
        >
          {state.notice}
        </p>
      )}

      {state.error && (
        <div className="mt-3">
          <ErrorAlert
            error={state.error}
            onDismiss={() => dispatch({ type: "error-cleared" })}
          />
        </div>
      )}

      <div className="mt-3 flex min-h-56 items-center justify-center overflow-hidden rounded-xl bg-black/35 p-3 ring-1 ring-white/8">
        {preview.url ? (
          // eslint-disable-next-line @next/next/no-img-element -- previews are content-addressed JPEGs served by the API
          <img
            key={`${preview.url}-${preview.version}`}
            src={preview.url}
            alt="编辑后的预览"
            className="max-h-[520px] w-full object-contain"
            onError={() => void retry()}
          />
        ) : (
          <p className="flex items-center gap-2 text-xs text-white/45">
            <ImageIcon className="size-4" />
            {preview.status === "error" ? "预览暂时不可用。" : "正在生成预览…"}
          </p>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[11px] text-white/35">
        <span>
          {preview.width > 0
            ? `${preview.width} × ${preview.height}`
            : "等待渲染尺寸"}
          {preview.status === "loading" && preview.url ? " · 更新中" : ""}
        </span>
        <div className="flex items-center gap-2">
          {preview.status === "error" && preview.error?.message && (
            <span className="text-red-200/80">{preview.error.message}</span>
          )}
          <button
            type="button"
            onClick={() => void retry()}
            className="min-h-11 rounded-lg border border-white/12 bg-white/[0.03] px-3 text-xs text-white/65 transition-colors hover:bg-white/[0.07] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            重新生成预览
          </button>
        </div>
      </div>

      <p className="mt-2 text-[11px] text-white/30">
        会话 ID 已写入 URL（?session=…），刷新页面会从服务端恢复。
      </p>
    </section>
  );
}

function EditorWorkspaceInner() {
  const apiStatus = useApiHealth();
  const limits = useRuntimeLimits();
  const [image, setImage] = useState<UploadedImage | null>(null);
  const [error, setError] = useState<UploadError | null>(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const { startSession } = useSessionActions();

  useSessionRestore();

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const handleFileSelected = useCallback(
    async (file: File) => {
      const validation = validateUploadFile(file, limits ?? undefined);
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
          void startSession(uploaded.imageId);
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
    },
    [limits, startSession],
  );

  const canRetry =
    pendingFile !== null && error !== null && !NON_RETRYABLE_CODES.has(error.code);

  const handleCancelUpload = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setUploading(false);
    setPendingFile(null);
    setImage(null);
    setError(null);
  }, []);

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
            <UploadDropzone
              onFileSelected={handleFileSelected}
              disabled={uploading}
              maxUploadBytes={limits?.maxUploadBytes}
            />
          )}

          {uploading && (
            <div className="mt-3 flex justify-center">
              <button
                type="button"
                onClick={handleCancelUpload}
                className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg border border-white/12 bg-white/[0.03] px-4 text-xs font-medium text-white/65 transition-colors hover:bg-white/[0.07] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                取消上传
              </button>
            </div>
          )}

          <SessionPreviewPanel />

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

export function EditorWorkspace() {
  return (
    <EditorProvider>
      <EditorWorkspaceInner />
    </EditorProvider>
  );
}
