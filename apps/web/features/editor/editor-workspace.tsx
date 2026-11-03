"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ErrorAlert } from "@/components/error-alert";
import {
  CheckCircleIcon,
  DownloadIcon,
  RefreshIcon,
  ShieldCheckIcon,
} from "@/components/icons";
import { AdjustmentPanel } from "@/features/editor/components/adjustment-panel";
import { CompareView } from "@/features/editor/components/compare-view";
import { CropOverlay } from "@/features/editor/components/crop-overlay";
import { ExportDialog } from "@/features/editor/components/export-dialog";
import { HistoryBar } from "@/features/editor/components/history-bar";
import { PreviewImage } from "@/features/editor/components/preview-image";
import { PreviewMonitor } from "@/features/editor/components/preview-monitor";
import { HealthIndicator } from "@/features/editor/health-indicator";
import { useExport } from "@/features/editor/hooks/use-export";
import { usePreviewVisibility } from "@/features/editor/hooks/use-preview-visibility";
import { useRenderPreview } from "@/features/editor/hooks/use-render-preview";
import {
  clearSessionUrl,
  useSessionActions,
  useSessionRestore,
} from "@/features/editor/hooks/use-session";
import {
  selectCanRedo,
  selectCanReset,
  selectCanUndo,
  selectCanSave,
  selectCanExport,
  selectIsDirty,
} from "@/features/editor/state/editor-reducer";
import { UploadDropzone } from "@/features/editor/upload-dropzone";
import { UploadResult } from "@/features/editor/upload-result";
import {
  EditorProvider,
  useEditorDispatch,
  useEditorState,
} from "@/features/editor/state/editor-context";
import {
  fetchConfig,
  fetchHealth,
  originalImageUrl,
  uploadImage,
} from "@/lib/api/client";
import { renderPreview } from "@/lib/api/sessions";
import { describeUploadError } from "@/lib/api/errors";
import { describeEditorError } from "@/lib/error-messages";
import {
  DEFAULT_ADJUSTMENTS,
  normalizeRecipe,
} from "@/lib/recipe";
import { validateUploadFile, type UploadLimits } from "@/lib/upload-validation";
import type { ApiStatus, UploadedImage, UploadError } from "@/types/image";
import type { Crop } from "@/types/session";

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

const toolButtonBase =
  "inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-white/12 bg-white/[0.03] px-3 text-xs text-white/70 transition-colors hover:bg-white/[0.07] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-40 aria-pressed:border-accent/40 aria-pressed:bg-accent/10 aria-pressed:text-accent";

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

function saveStatusLabel(status: "saved" | "saving" | "unsaved" | "error"): string {
  switch (status) {
    case "saving":
      return "保存中…";
    case "unsaved":
      return "有未保存的调整";
    case "error":
      return "保存失败";
    default:
      return "已保存";
  }
}

interface CropBase {
  url: string;
  width: number;
  height: number;
}

interface EditorStageProps {
  image: UploadedImage | null;
  uploading: boolean;
  onFileSelected: (file: File) => void;
  onStartOver: () => void;
}

function EditorStage({
  image,
  uploading,
  onFileSelected,
  onStartOver,
}: EditorStageProps) {
  const state = useEditorState();
  const dispatch = useEditorDispatch();
  const { commit, undo, redo, reset, activate } = useSessionActions();
  const { preview, requestFinal, retry } = useRenderPreview();
  const { sentinelRef: previewSentinelRef, isVisible: previewVisible } =
    usePreviewVisibility();
  const exporter = useExport();

  const [compareOpen, setCompareOpen] = useState(false);
  const [cropMode, setCropMode] = useState(false);
  const [cropBase, setCropBase] = useState<CropBase | null>(null);
  const [cropBaseError, setCropBaseError] = useState<string | null>(null);
  const [cropAttempt, setCropAttempt] = useState(0);
  const [cropBefore, setCropBefore] = useState<Crop | null>(null);
  const [exportOpen, setExportOpen] = useState(false);
  const [commitNonce, setCommitNonce] = useState(0);
  const commitNonceRef = useRef(0);
  const commitInFlightRef = useRef(false);
  const pendingCommitRef = useRef(false);
  const revisionRef = useRef(state.activeRevisionId);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const dirty = selectIsDirty(state);
  const saving = state.save.status === "saving";
  const canSave = selectCanSave(state);
  const canExport = selectCanExport(state);

  const handleCommit = useCallback(async () => {
    if (commitInFlightRef.current || state.save.status === "saving") {
      pendingCommitRef.current = true;
      return;
    }
    if (!selectIsDirty(state)) {
      return;
    }
    commitInFlightRef.current = true;
    try {
      await requestFinal();
      await commit();
    } finally {
      commitInFlightRef.current = false;
      if (pendingCommitRef.current) {
        pendingCommitRef.current = false;
        setCommitNonce((value) => value + 1);
      }
    }
  }, [commit, requestFinal, state]);

  useEffect(() => {
    if (commitNonce === commitNonceRef.current) {
      return;
    }
    commitNonceRef.current = commitNonce;
    void handleCommit();
  }, [commitNonce, handleCommit]);

  useEffect(() => {
    if (revisionRef.current === state.activeRevisionId) {
      return;
    }
    revisionRef.current = state.activeRevisionId;
    void requestFinal();
  }, [requestFinal, state.activeRevisionId]);

  const sessionId = state.sessionId;
  const rotationDeg = state.draft.adjustments.rotationDeg;

  useEffect(() => {
    if (!cropMode || sessionId === null) {
      return;
    }
    let cancelled = false;
    const controller = new AbortController();
    const recipe = normalizeRecipe({
      schemaVersion: "1.0",
      styleId: "natural",
      styleStrength: 0,
      adjustments: { ...DEFAULT_ADJUSTMENTS, rotationDeg },
      rationale: [],
      warnings: [],
    });

    renderPreview(sessionId, { recipe, quality: "final" }, controller.signal)
      .then((result) => {
        if (!cancelled) {
          setCropBase({
            url: result.previewUrl,
            width: result.width,
            height: result.height,
          });
          setCropBaseError(null);
        }
      })
      .catch((error: unknown) => {
        if (!cancelled && !controller.signal.aborted) {
          setCropBase(null);
          setCropBaseError(describeEditorError(error).message);
        }
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [cropAttempt, cropMode, rotationDeg, sessionId]);

  const requestCommit = useCallback(() => {
    setCommitNonce((value) => value + 1);
  }, []);

  const handleOpenCrop = useCallback(() => {
    setCompareOpen(false);
    setCropBefore(state.draft.adjustments.crop ?? null);
    setCropBase(null);
    setCropBaseError(null);
    setCropMode(true);
  }, [state.draft.adjustments.crop]);

  const handleCancelCrop = useCallback(() => {
    dispatch({ type: "draft-crop", crop: cropBefore });
    setCropMode(false);
  }, [cropBefore, dispatch]);

  const handleApplyCrop = useCallback(() => {
    setCropMode(false);
    requestCommit();
  }, [requestCommit]);

  const handleToggleCompare = useCallback(() => {
    if (cropMode) {
      dispatch({ type: "draft-crop", crop: cropBefore });
      setCropMode(false);
    }
    setCompareOpen((value) => !value);
  }, [cropBefore, cropMode, dispatch]);

  const handleReturnToPreview = useCallback(() => {
    const surface = document.getElementById("editor-preview-surface");
    const reduceMotion =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    surface?.scrollIntoView?.({
      behavior: reduceMotion ? "auto" : "smooth",
      block: "center",
    });
  }, []);

  const handleExport = useCallback(
    (format: "jpeg" | "png", quality: number | null) => {
      if (state.activeRevisionId === null) {
        return;
      }
      void exporter.exportImage({
        revisionId: state.activeRevisionId,
        format,
        quality,
      });
    },
    [exporter, state.activeRevisionId],
  );

  if (state.sessionId === null) {
    return null;
  }

  const previewError =
    preview.status === "error" && preview.error?.message ? preview.error.message : null;
  const monitorVisible =
    state.phase === "ready" &&
    !previewVisible &&
    preview.url !== null &&
    !compareOpen &&
    !cropMode &&
    !exportOpen;

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
      <div className="editor-preview-column grid content-start gap-4">
        <section
          aria-labelledby="editor-preview-heading"
          className="editor-preview-card rounded-2xl border border-white/8 bg-black/20 p-4 sm:p-5"
        >
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 id="editor-preview-heading" className="text-sm font-medium text-white">
                编辑预览
              </h3>
              <p className="editor-preview-meta mt-1 font-mono text-[10px] uppercase tracking-[0.14em] text-white/30">
                Session {state.sessionId.slice(0, 8)} · Revision{" "}
                {state.activeRevisionId?.slice(0, 8) ?? "—"}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="editor-preview-quality rounded-full border border-white/10 px-2.5 py-1 font-mono text-[10px] text-white/45">
                {preview.quality === "draft"
                  ? "草稿预览"
                  : preview.quality === "final"
                    ? "终稿预览"
                    : "等待渲染"}
              </span>
              <span
                className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] ${
                  state.save.status === "error"
                    ? "border-red-300/30 text-red-100"
                    : state.save.status === "unsaved"
                      ? "border-amber-300/30 text-amber-100"
                      : "border-white/10 text-white/45"
                }`}
              >
                <span aria-hidden="true">
                  {state.save.status === "saved" ? "●" : "○"}
                </span>
                {saveStatusLabel(state.save.status)}
              </span>
            </div>
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              aria-pressed={compareOpen}
              onClick={handleToggleCompare}
              disabled={saving}
              className={toolButtonBase}
            >
              前后对比
            </button>
            <button
              type="button"
              aria-pressed={cropMode}
              onClick={cropMode ? handleCancelCrop : handleOpenCrop}
              disabled={saving}
              className={toolButtonBase}
            >
              裁切
            </button>
            <button
              type="button"
              onClick={() => setExportOpen(true)}
              disabled={!canExport || dirty || saving}
              title={
                dirty
                  ? "请先保存当前调整，再导出对应的终稿。"
                  : "从原图渲染并导出当前已保存版本。"
              }
              className={toolButtonBase}
            >
              <DownloadIcon className="size-3.5" />
              导出
            </button>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className={toolButtonBase}
            >
              更换照片
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              aria-label="更换照片"
              className="sr-only"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) {
                  onFileSelected(file);
                }
                event.target.value = "";
              }}
            />
            {image && (
              <a
                href={originalImageUrl(image.imageId, true)}
                download={image.originalName}
                className={toolButtonBase}
              >
                <DownloadIcon className="size-3.5" />
                下载原图
              </a>
            )}
            <button type="button" onClick={onStartOver} className={toolButtonBase}>
              重新开始
            </button>
          </div>

          {uploading && (
            <p role="status" className="mt-3 text-[11px] text-white/45">
              正在上传新照片，完成后会创建新的编辑会话…
            </p>
          )}

          {state.notice && (
            <p
              role="status"
              className="mt-3 rounded-lg border border-amber-300/25 bg-amber-300/10 px-3 py-2 text-xs text-amber-100"
            >
              {state.notice}
              <button
                type="button"
                onClick={() => dispatch({ type: "notice-cleared" })}
                aria-label="关闭提示"
                className="ml-2 text-amber-200/70 underline-offset-2 hover:underline"
              >
                知道了
              </button>
            </p>
          )}

          {state.error && (
            <div className="mt-3">
              <ErrorAlert
                error={state.error}
                stage="编辑操作"
                onDismiss={() => dispatch({ type: "error-cleared" })}
              />
            </div>
          )}

          <div className="mt-3">
            {compareOpen && state.activeRevisionId ? (
              <CompareView
                sessionId={state.sessionId}
                revisionId={state.activeRevisionId}
                dirty={dirty}
                onClose={() => setCompareOpen(false)}
              />
            ) : cropMode ? (
              cropBase ? (
                <CropOverlay
                  imageUrl={cropBase.url}
                  canvasWidth={cropBase.width}
                  canvasHeight={cropBase.height}
                  crop={state.draft.adjustments.crop ?? null}
                  disabled={saving}
                  onChange={(crop) => dispatch({ type: "draft-crop", crop })}
                  onApply={handleApplyCrop}
                  onCancel={handleCancelCrop}
                />
              ) : cropBaseError ? (
                <div
                  role="alert"
                  className="flex flex-col items-center gap-3 rounded-xl border border-red-400/25 bg-red-400/[0.06] px-6 py-12 text-center"
                >
                  <p className="text-xs text-red-100">{cropBaseError}</p>
                  <button
                    type="button"
                    onClick={() => {
                      setCropBaseError(null);
                      setCropAttempt((value) => value + 1);
                    }}
                    className="min-h-11 rounded-lg border border-red-300/25 bg-red-300/10 px-3 text-xs text-red-100"
                  >
                    重新获取裁切基准
                  </button>
                </div>
              ) : (
                <div className="flex min-h-64 items-center justify-center rounded-xl border border-white/8 bg-black/35">
                  <p className="text-xs text-white/45">正在获取旋转后的裁切基准…</p>
                </div>
              )
            ) : (
              <>
                <PreviewImage
                  id="editor-preview-surface"
                  containerRef={previewSentinelRef}
                  preview={preview}
                  alt="编辑后的预览"
                  errorMessage={previewError}
                  onError={() => void retry()}
                  className="editor-preview-canvas relative flex min-h-48 items-center justify-center overflow-hidden rounded-xl bg-black/35 p-3 ring-1 ring-white/8 sm:min-h-64"
                  imageClassName="editor-preview-image w-full object-contain"
                />

                <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[11px] text-white/35">
                  <span>
                    {preview.width > 0
                      ? `${preview.width} × ${preview.height}`
                      : "等待渲染尺寸"}
                    {preview.status === "loading" && preview.url ? " · 更新中" : ""}
                  </span>
                  <div className="flex items-center gap-2">
                    {previewError && (
                      <span role="alert" className="text-red-700">
                        生成预览失败：{previewError} · {preview.error?.code}
                        {preview.error?.requestId
                          ? ` · 请求 ID ${preview.error.requestId}`
                          : ""}
                      </span>
                    )}
                    <button
                      type="button"
                      onClick={() => void retry()}
                      className="inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-white/12 bg-white/[0.03] px-3 text-xs text-white/65 transition-colors hover:bg-white/[0.07] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                    >
                      <RefreshIcon className="size-3.5" />
                      重新生成预览
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>

          {(dirty || state.save.status === "error") && (
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-300/20 bg-amber-300/[0.06] px-3 py-2">
              <p className="text-[11px] text-amber-100/85">
                {state.save.status === "error"
                  ? state.save.error?.message ?? "保存失败，请稍后重试。"
                  : "调整会自动提交；也可以手动保存当前版本。"}
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={requestCommit}
                  disabled={!canSave && state.save.status !== "error"}
                  className="min-h-11 rounded-lg border border-amber-300/25 bg-amber-300/10 px-3 text-xs text-amber-100 transition-colors hover:bg-amber-300/20 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-200 disabled:opacity-40"
                >
                  {state.save.status === "error" ? "重试保存" : "保存修改"}
                </button>
                {state.save.status === "error" && dirty && (
                  <button
                    type="button"
                    onClick={() => dispatch({ type: "draft-discard" })}
                    className="min-h-11 rounded-lg border border-white/12 px-3 text-xs text-white/55 transition-colors hover:bg-white/[0.05] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                  >
                    放弃未保存调整
                  </button>
                )}
              </div>
            </div>
          )}

          <p className="editor-preview-hint mt-2 text-[11px] text-white/30">
            会话 ID 已写入 URL（?session=…），刷新页面会从服务端恢复。
          </p>
        </section>

        <div className="editor-history">
          <HistoryBar
            canUndo={selectCanUndo(state)}
            canRedo={selectCanRedo(state)}
            canReset={selectCanReset(state)}
            busy={saving}
            items={state.history}
            activeRevisionId={state.activeRevisionId}
            onUndo={() => void undo()}
            onRedo={() => void redo()}
            onReset={() => void reset()}
            onActivate={(revisionId) => void activate(revisionId)}
          />
        </div>
      </div>

      <aside aria-label="参数面板" className="editor-adjustment-panel min-w-0">
        <div
          className="editor-adjustment-scroll rounded-2xl border border-white/8 bg-black/20 p-4"
          data-testid="adjustment-panel-scroll"
        >
          <AdjustmentPanel
            adjustments={state.draft.adjustments}
            disabled={cropMode || compareOpen}
            onChange={(key, value) => dispatch({ type: "draft-adjustment", key, value })}
            onCommit={requestCommit}
            onOpenCrop={handleOpenCrop}
            onClearCrop={() => {
              dispatch({ type: "draft-crop", crop: null });
              requestCommit();
            }}
          />
        </div>
      </aside>

      <PreviewMonitor
        preview={preview}
        visible={monitorVisible}
        onReturn={handleReturnToPreview}
      />

      <ExportDialog
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        state={exporter.state}
        dirty={dirty}
        disabled={!canExport}
        onExport={handleExport}
      />
    </div>
  );
}

function EditorWorkspaceInner() {
  const apiStatus = useApiHealth();
  const limits = useRuntimeLimits();
  const state = useEditorState();
  const dispatch = useEditorDispatch();
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

  const handleStartOver = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setUploading(false);
    setPendingFile(null);
    setImage(null);
    setError(null);
    clearSessionUrl();
    dispatch({ type: "reset-editor" });
  }, [dispatch]);

  const inEditor = state.phase === "ready" || state.phase === "exporting";

  return (
    <section aria-labelledby="workspace-heading" className="relative">
      <div className="overflow-clip rounded-3xl border border-white/10 bg-[#0c0d0f]/90 shadow-[0_30px_80px_-30px_rgba(0,0,0,0.9)] backdrop-blur-sm">
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
                Edit · Render · Export
              </p>
            </div>
          </div>
          <HealthIndicator status={apiStatus} />
        </div>

        <div className="p-3 sm:p-6">
          {error && (
            <ErrorAlert
              error={error}
              stage="上传图片"
              retryLabel="重试上传"
              onRetry={canRetry && pendingFile ? () => void handleFileSelected(pendingFile) : undefined}
              onDismiss={() => setError(null)}
            />
          )}

          {!inEditor && state.error && (
            <ErrorAlert
              error={state.error}
              stage={image ? "创建编辑会话" : undefined}
              retryLabel="重试创建会话"
              onRetry={image ? () => void startSession(image.imageId) : undefined}
              onDismiss={() => dispatch({ type: "error-cleared" })}
            />
          )}

          {inEditor ? (
            <EditorStage
              image={image}
              uploading={uploading}
              onFileSelected={handleFileSelected}
              onStartOver={handleStartOver}
            />
          ) : (
            <>
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

              {state.phase === "creatingSession" && (
                <p className="mt-4 rounded-xl border border-white/8 bg-white/[0.02] px-4 py-3 text-xs text-white/45">
                  正在准备编辑会话…
                </p>
              )}
            </>
          )}

          <p className="sr-only" role="status" aria-live="polite">
            {uploading
              ? "正在上传照片"
              : inEditor
                ? "已进入编辑工作区"
                : image
                  ? "照片上传完成"
                  : ""}
          </p>
        </div>

        <div className="flex flex-col gap-2 border-t border-white/8 bg-black/15 px-4 py-3 text-[11px] text-white/35 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <span className="inline-flex items-center gap-2">
            <ShieldCheckIcon className="size-3.5 text-accent/70" />
            原图只读保存；预览、渲染与导出全部在本机服务完成。
          </span>
          <span className="inline-flex items-center gap-2">
            <CheckCircleIcon className="size-3.5 text-white/25" />
            导出移除 EXIF/GPS 并嵌入 sRGB；阶段 2 不调用 AI 模型。
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
