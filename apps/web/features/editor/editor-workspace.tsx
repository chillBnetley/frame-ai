"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ErrorAlert } from "@/components/error-alert";
import {
  CheckCircleIcon,
  DownloadIcon,
  RefreshIcon,
  ShieldCheckIcon,
} from "@/components/icons";
import { AnalysisPanel } from "@/features/analysis/components/analysis-panel";
import { useAnalysis } from "@/features/analysis/hooks/use-analysis";
import { AdjustmentPanel } from "@/features/editor/components/adjustment-panel";
import { ColorGradingPanel } from "@/features/editor/components/color-grading-panel";
import { CompareView } from "@/features/editor/components/compare-view";
import { CropOverlay } from "@/features/editor/components/crop-overlay";
import { CurveEditor } from "@/features/editor/components/curve-editor";
import { DeletePhotoDialog } from "@/features/editor/components/delete-photo-dialog";
import { ExportDialog } from "@/features/editor/components/export-dialog";
import { HslPanel } from "@/features/editor/components/hsl-panel";
import { HistoryBar } from "@/features/editor/components/history-bar";
import { LocalAdjustmentsPanel } from "@/features/editor/components/local-adjustments-panel";
import { PreviewImage } from "@/features/editor/components/preview-image";
import { PreviewMonitor } from "@/features/editor/components/preview-monitor";
import { HealthIndicator } from "@/features/editor/health-indicator";
import { CreativeStudio } from "@/features/generative/studio/creative-studio";
import type { StudioCapability } from "@/features/generative/studio/use-studio-state";
import { PhotographerPanel } from "@/features/photographer/components/photographer-panel";
import { usePhotographer } from "@/features/photographer/hooks/use-photographer";
import { usePhotographerChat } from "@/features/photographer/hooks/use-photographer-chat";
import { usePhotographerCritique } from "@/features/photographer/hooks/use-photographer-critique";
import { useStyles } from "@/features/photographer/hooks/use-styles";
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
  selectProposalPreviewing,
} from "@/features/editor/state/editor-reducer";
import { UploadDropzone } from "@/features/editor/upload-dropzone";
import { UploadResult } from "@/features/editor/upload-result";
import {
  EditorProvider,
  useEditorDispatch,
  useEditorState,
} from "@/features/editor/state/editor-context";
import {
  createSemanticMask,
  deleteImage,
  fetchConfig,
  fetchHealth,
  originalImageUrl,
  uploadImage,
} from "@/lib/api/client";
import { renderPreview } from "@/lib/api/sessions";
import { createGenerativeMask } from "@/lib/api/generative";
import { describeUploadError } from "@/lib/api/errors";
import {
  describeEditorError,
  ERROR_FALLBACK_MESSAGE,
} from "@/lib/error-messages";
import { nextRenderSeq } from "@/lib/render-seq";
import {
  DEFAULT_ADJUSTMENTS,
  normalizeColorGrading,
  normalizeHsl,
  normalizeRecipe,
  withColorGradingSet,
  withColorGradeZone,
  withCurveSet,
  withHsl,
  withHslSet,
} from "@/lib/recipe";
import {
  FILE_ACCEPT_ATTRIBUTE,
  validateUploadFile,
  type UploadLimits,
} from "@/lib/upload-validation";
import type { ApiStatus, UploadedImage, UploadError } from "@/types/image";
import type { Crop, SessionState } from "@/types/session";

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
  "inline-flex min-h-11 items-center gap-1.5 rounded-xl border border-white/12 bg-gradient-to-b from-white/[0.12] to-white/[0.03] px-3 text-xs text-white/70 shadow-[inset_0_1px_0_rgba(255,255,255,0.16),0_2px_8px_rgba(20,35,28,0.04)] transition-all duration-200 hover:-translate-y-px hover:border-accent/30 hover:from-accent/[0.12] hover:to-accent/[0.04] hover:text-white hover:shadow-[inset_0_1px_0_rgba(255,255,255,0.32),0_5px_14px_rgba(39,122,104,0.12)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:translate-y-0 aria-pressed:border-accent/40 aria-pressed:from-accent/15 aria-pressed:to-accent/[0.06] aria-pressed:text-accent";

const CROP_BASE_MAX_AUTO_RETRIES = 1;
const CROP_BASE_RETRYABLE_CODES = new Set([
  "render_superseded",
  "request_timeout",
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

interface RuntimeConfigState {
  limits: UploadLimits | null;
  layersEnabled: boolean;
  semanticMasks: {
    enabled: boolean;
    person: boolean;
    sky: boolean;
    models: { person: string | null; sky: string | null };
  };
}

function useRuntimeLimits(): RuntimeConfigState {
  const [state, setState] = useState<RuntimeConfigState>({
    limits: null,
    layersEnabled: false,
    semanticMasks: {
      enabled: false,
      person: false,
      sky: false,
      models: { person: null, sky: null },
    },
  });

  useEffect(() => {
    let active = true;

    fetchConfig()
      .then((config) => {
        if (active) {
          const semantic = config.features?.semanticMasks;
          const models = config.features?.semanticMaskModels;
          setState({
            limits: {
              maxUploadBytes: config.maxUploadBytes,
              allowedMimeTypes: config.allowedMimeTypes,
            },
            layersEnabled: config.features?.layers === true,
            semanticMasks: {
              enabled: semantic?.enabled === true,
              person: semantic?.person === true,
              sky: semantic?.sky === true,
              models: {
                person: models?.person ?? null,
                sky: models?.sky ?? null,
              },
            },
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

  return state;
}

function saveStatusLabel(
  status: "saved" | "saving" | "unsaved" | "error",
): string {
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

interface StudioPreset {
  maskId: string;
  capability: StudioCapability;
}

interface EditorStageProps {
  image: UploadedImage | null;
  uploading: boolean;
  layersEnabled: boolean;
  semanticMasks: RuntimeConfigState["semanticMasks"];
  onFileSelected: (file: File) => void;
  onPhotoDeleted: () => void;
}

function EditorStage({
  image,
  uploading,
  layersEnabled,
  semanticMasks,
  onFileSelected,
  onPhotoDeleted,
}: EditorStageProps) {
  const state = useEditorState();
  const dispatch = useEditorDispatch();
  const { commit, undo, redo, reset, activate, reloadHistory } = useSessionActions();
  const { preview, requestFinal, retry } = useRenderPreview();
  const { sentinelRef: previewSentinelRef, isVisible: previewVisible } =
    usePreviewVisibility();
  const exporter = useExport();
  const analysis = useAnalysis(uploading ? null : state.imageId);
  const photographer = usePhotographer(analysis);
  const feedback = photographer.feedback;
  const photographerChat = usePhotographerChat(analysis);
  const photographerCritique = usePhotographerCritique(analysis);

  const [analysisOpen, setAnalysisOpen] = useState(false);
  const [photographerOpen, setPhotographerOpen] = useState(false);
  const styles = useStyles(photographerOpen);
  const [compareOpen, setCompareOpen] = useState(false);
  const [studioOpen, setStudioOpen] = useState(false);
  const [studioPreset, setStudioPreset] = useState<StudioPreset | null>(null);
  const [cropMode, setCropMode] = useState(false);
  const [cropBase, setCropBase] = useState<CropBase | null>(null);
  const [cropBaseError, setCropBaseError] = useState<string | null>(null);
  const [cropAttempt, setCropAttempt] = useState(0);
  const cropBaseRetriesRef = useRef(0);
  const cropBaseRotationRef = useRef<number | null>(null);
  const [cropBefore, setCropBefore] = useState<Crop | null>(null);
  const [exportOpen, setExportOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
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
  const panelOpen = analysisOpen || photographerOpen;
  const proposalPreviewing = selectProposalPreviewing(state);
  const proposalOriginal =
    state.proposal.status === "ready" && state.proposal.view === "original";

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

  // Resetting is a preference signal, so it is recorded with the revision that
  // shows which parameters the reset moved.
  const handleReset = useCallback(async () => {
    const outcome = await reset();
    if (!outcome.ok) {
      return;
    }
    await feedback.record({
      action: "reset",
      source: null,
      planId: null,
      revisionId: outcome.revisionId,
    });
  }, [feedback, reset]);

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
    if (cropBaseRotationRef.current !== rotationDeg) {
      cropBaseRotationRef.current = rotationDeg;
      cropBaseRetriesRef.current = 0;
    }
    let cancelled = false;
    const controller = new AbortController();
    const recipe = normalizeRecipe({
      schemaVersion: "2.0",
      styleId: "natural",
      styleStrength: 0,
      adjustments: { ...DEFAULT_ADJUSTMENTS, rotationDeg },
      rationale: [],
      warnings: [],
    });

    renderPreview(
      sessionId,
      { recipe, quality: "final" },
      controller.signal,
      nextRenderSeq(),
    )
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
        if (cancelled || controller.signal.aborted) {
          return;
        }
        const described = describeEditorError(error);
        if (
          CROP_BASE_RETRYABLE_CODES.has(described.code) &&
          cropBaseRetriesRef.current < CROP_BASE_MAX_AUTO_RETRIES
        ) {
          cropBaseRetriesRef.current += 1;
          setCropAttempt((value) => value + 1);
          return;
        }
        setCropBase(null);
        setCropBaseError(described.message.trim() || ERROR_FALLBACK_MESSAGE);
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
    cropBaseRetriesRef.current = 0;
    cropBaseRotationRef.current = state.draft.adjustments.rotationDeg;
    setCropMode(true);
  }, [state.draft.adjustments.crop, state.draft.adjustments.rotationDeg]);

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

  const handleOpenStudio = useCallback(
    (preset: StudioPreset | null = null) => {
      setStudioPreset(preset);
      setAnalysisOpen(false);
      setPhotographerOpen(false);
      setCompareOpen(false);
      setStudioOpen(true);
      if (selectIsDirty(state)) {
        requestCommit();
      }
    },
    [requestCommit, state],
  );

  const handleUseSemanticForGenerative = useCallback(
    async (kind: "person" | "sky") => {
      if (state.sessionId === null) {
        return;
      }
      const created = await createGenerativeMask({
        sessionId: state.sessionId,
        kind: "semantic",
        definition: { semanticClass: kind, expand: 0 },
        feather: 0,
        inverted: false,
      });
      handleOpenStudio({ maskId: created.maskId, capability: "remove" });
    },
    [handleOpenStudio, state.sessionId],
  );

  // Accepting a candidate creates the revision server-side, so the local head
  // and the history strip are re-read rather than patched by hand.
  const handleGenerativeAccepted = useCallback(
    async (next: SessionState) => {
      dispatch({ type: "session-replaced", state: next });
      await reloadHistory();
    },
    [dispatch, reloadHistory],
  );

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
    (
      format: "jpeg" | "png" | "tiff",
      quality: number | null,
      maxEdge: number | null,
      bitDepth: 8 | 16,
    ) => {
      if (state.activeRevisionId === null) {
        return;
      }
      void exporter.exportImage({
        revisionId: state.activeRevisionId,
        format,
        quality,
        maxEdge,
        bitDepth,
      });
    },
    [exporter, state.activeRevisionId],
  );

  const handleCloseExport = useCallback(() => {
    if (exporter.state.status === "exporting") {
      void exporter.cancel();
    }
    setExportOpen(false);
  }, [exporter, setExportOpen]);

  const handleOpenDelete = useCallback(() => {
    setDeleteError(null);
    setDeleteOpen(true);
  }, []);

  const handleConfirmDelete = useCallback(async () => {
    if (deleting || state.imageId === null) {
      return;
    }
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteImage(state.imageId);
      setDeleteOpen(false);
      onPhotoDeleted();
    } catch (error) {
      setDeleteError(describeEditorError(error).message);
    } finally {
      setDeleting(false);
    }
  }, [deleting, onPhotoDeleted, state.imageId]);

  if (state.sessionId === null) {
    return null;
  }

  const previewError =
    preview.status === "error" && preview.error?.message
      ? preview.error.message
      : null;
  const monitorVisible =
    state.phase === "ready" &&
    !previewVisible &&
    preview.url !== null &&
    !studioOpen &&
    !compareOpen &&
    !cropMode &&
    !exportOpen &&
    !proposalOriginal;

  const historyBar = (
    <HistoryBar
      canUndo={selectCanUndo(state)}
      canRedo={selectCanRedo(state)}
      canReset={selectCanReset(state)}
      busy={saving}
      items={state.history}
      activeRevisionId={state.activeRevisionId}
      onUndo={() => void undo()}
      onRedo={() => void redo()}
      onReset={() => void handleReset()}
      onActivate={(revisionId) => void activate(revisionId)}
    />
  );

  return (
    <div
      className={
        panelOpen
          ? "grid gap-4 lg:grid-cols-[minmax(0,2.2fr)_minmax(280px,0.9fr)] xl:grid-cols-[minmax(0,2fr)_320px_300px]"
          : "grid gap-4 lg:grid-cols-[minmax(0,2.2fr)_minmax(280px,0.9fr)]"
      }
    >
      {studioOpen && (
        <div className="min-w-0 lg:col-span-2 xl:col-span-3">
          <CreativeStudio
            sessionId={state.sessionId}
            previewImageUrl={preview.url}
            baseWidth={state.baseWidth}
            baseHeight={state.baseHeight}
            gradedBaseAvailable={
              state.committed.adjustments.crop == null &&
              state.committed.adjustments.rotationDeg === 0
            }
            originalImageUrl={state.imageId ? originalImageUrl(state.imageId) : null}
            analysisReport={analysis.report}
            initialMaskId={studioPreset?.maskId ?? null}
            initialCapability={studioPreset?.capability}
            subjectMaskAvailable={state.baseGeneratedAssetId === null}
            onResultAccepted={handleGenerativeAccepted}
            onExit={() => setStudioOpen(false)}
            historySlot={historyBar}
          />
        </div>
      )}
      <div
        className={`editor-preview-column grid content-start gap-4 ${
          panelOpen && !studioOpen ? "lg:col-start-1 lg:row-start-1" : ""
        } ${studioOpen ? "hidden" : ""}`}
      >
        <section
          aria-labelledby="editor-preview-heading"
          className="editor-preview-card rounded-[28px] border border-white/10 bg-black/20 p-3 shadow-[0_18px_50px_-32px_rgba(24,50,38,0.22),inset_0_1px_0_rgba(255,255,255,0.8)] sm:p-4"
        >
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3
                id="editor-preview-heading"
                className="text-sm font-medium text-white"
              >
                编辑预览
              </h3>
              <p className="editor-preview-meta mt-1 font-mono text-[10px] uppercase tracking-[0.14em] text-white/30">
                Session {state.sessionId.slice(0, 8)} · Revision{" "}
                {state.activeRevisionId?.slice(0, 8) ?? "—"}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="editor-preview-quality rounded-full border border-white/10 px-2.5 py-1 font-mono text-[10px] text-white/45">
                {proposalPreviewing
                  ? "AI 方案预览"
                  : proposalOriginal
                    ? "原图"
                    : preview.quality === "draft"
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
                    ? "border-amber-300/30 text-amber-950"
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
              aria-pressed={analysisOpen}
              aria-expanded={analysisOpen}
              aria-controls="analysis-panel"
              onClick={() => {
                setStudioOpen(false);
                setPhotographerOpen(false);
                setAnalysisOpen((value) => !value);
              }}
              disabled={uploading}
              className={toolButtonBase}
            >
              AI 摄影分析
              {analysis.running && (
                <span className="font-mono text-[10px] text-accent">
                  分析中
                </span>
              )}
            </button>
            <button
              type="button"
              aria-pressed={photographerOpen}
              aria-expanded={photographerOpen}
              aria-controls="photographer-panel"
              onClick={() => {
                setStudioOpen(false);
                setAnalysisOpen(false);
                setPhotographerOpen((value) => !value);
              }}
              disabled={uploading}
              className={toolButtonBase}
            >
              AI 自动优化
              {photographer.proposal.status === "loading" && (
                <span className="font-mono text-[10px] text-accent">
                  生成中
                </span>
              )}
            </button>
            <button
              type="button"
              aria-pressed={studioOpen}
              onClick={() => handleOpenStudio()}
              disabled={uploading || cropMode || saving}
              title={
                cropMode
                  ? "请先完成或取消裁切，再进入创意工作台。"
                  : "在统一工作台中使用扩图、智能消除与局部生成。"
              }
              className={toolButtonBase}
            >
              AI 创意工作台
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
              accept={FILE_ACCEPT_ATTRIBUTE}
              aria-label="更换照片"
              className="sr-only"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) {
                  setAnalysisOpen(false);
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
            <button
              type="button"
              onClick={handleOpenDelete}
              disabled={uploading || saving || deleting || state.imageId === null}
              title="永久删除原图、会话与本机派生数据"
              className="inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-red-300/25 bg-red-300/[0.06] px-3 text-xs text-red-100 transition-colors hover:bg-red-300/[0.12] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-200 disabled:cursor-not-allowed disabled:opacity-40"
            >
              删除照片
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
              className="mt-3 rounded-lg border border-amber-300/25 bg-amber-300/10 px-3 py-2 text-xs text-amber-950"
            >
              {state.notice}
              <button
                type="button"
                onClick={() => dispatch({ type: "notice-cleared" })}
                aria-label="关闭提示"
                className="ml-2 text-amber-900 underline-offset-2 hover:underline"
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

          <div className="editor-preview-body mt-3">
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
                      cropBaseRetriesRef.current = 0;
                      setCropAttempt((value) => value + 1);
                    }}
                    className="min-h-11 rounded-lg border border-red-300/25 bg-red-300/10 px-3 text-xs text-red-100"
                  >
                    重新获取裁切基准
                  </button>
                </div>
              ) : (
                <div className="flex min-h-64 items-center justify-center rounded-xl border border-white/8 bg-black/35">
                  <p className="text-xs text-white/45">
                    正在获取旋转后的裁切基准…
                  </p>
                </div>
              )
            ) : proposalOriginal && state.imageId ? (
              <div
                data-testid="photographer-original"
                className="editor-preview-canvas relative flex min-h-48 items-center justify-center overflow-hidden rounded-xl bg-black/35 p-3 ring-1 ring-white/8 sm:min-h-64"
              >
                {/* eslint-disable-next-line @next/next/no-img-element -- the API serves the read-only original */}
                <img
                  src={originalImageUrl(state.imageId)}
                  alt="原图"
                  className="editor-preview-image w-full object-contain"
                />
                <span className="absolute left-3 top-3 rounded-full border border-white/20 bg-black/65 px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.14em] text-white/80">
                  原图
                </span>
              </div>
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
                    {preview.status === "loading" && preview.url
                      ? " · 更新中"
                      : ""}
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
              <p className="text-[11px] text-amber-950">
                {state.save.status === "error"
                  ? (state.save.error?.message ?? "保存失败，请稍后重试。")
                  : "调整会自动提交；也可以手动保存当前版本。"}
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={requestCommit}
                  disabled={!canSave && state.save.status !== "error"}
                  className="min-h-11 rounded-lg border border-amber-300/25 bg-amber-300/10 px-3 text-xs text-amber-950 transition-colors hover:bg-amber-300/20 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-200 disabled:opacity-40"
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

        <div className="editor-history">{historyBar}</div>
      </div>

      <AnalysisPanel
        open={analysisOpen}
        imageId={state.imageId ?? ""}
        analysis={analysis}
        onClose={() => setAnalysisOpen(false)}
        className={
          analysisOpen
            ? "lg:col-start-1 lg:row-start-2 xl:col-start-2 xl:row-start-1"
            : undefined
        }
      />

      <PhotographerPanel
        open={photographerOpen}
        onClose={() => setPhotographerOpen(false)}
        imageId={state.imageId ?? ""}
        analysis={analysis}
        proposal={photographer.proposal}
        canAccept={photographer.canAccept}
        dirty={dirty}
        styles={styles}
        chat={photographerChat}
        critique={photographerCritique}
        selectedStyleId={photographer.styleId}
        styleStrength={photographer.styleStrength}
        feedback={photographer.feedback}
        onStart={photographer.start}
        onRetry={photographer.retry}
        onCancel={photographer.cancel}
        onView={photographer.showView}
        onAccept={() => void photographer.accept()}
        onAbandon={photographer.abandon}
        onSelectStyle={photographer.selectStyle}
        onStyleStrengthChange={photographer.setStyleStrength}
        onStyleStrengthCommit={photographer.commitStyleStrength}
        className={
          photographerOpen
            ? "lg:col-start-1 lg:row-start-2 xl:col-start-2 xl:row-start-1"
            : undefined
        }
      />

      <aside
        aria-label="参数面板"
        className={`editor-adjustment-panel min-w-0 ${
          panelOpen ? "lg:col-start-2 lg:row-start-1 xl:col-start-3" : ""
        } ${studioOpen ? "hidden" : ""}`}
      >
        <div
          className="editor-adjustment-scroll rounded-2xl border border-white/8 bg-black/20 p-4"
          data-testid="adjustment-panel-scroll"
        >
          <AdjustmentPanel
            adjustments={state.draft.adjustments}
            disabled={cropMode || compareOpen}
            onChange={(key, value) =>
              dispatch({ type: "draft-adjustment", key, value })
            }
            onCommit={requestCommit}
            onOpenCrop={handleOpenCrop}
            onClearCrop={() => {
              dispatch({ type: "draft-crop", crop: null });
              requestCommit();
            }}
          />
          <div className="mt-5">
            <CurveEditor
              curve={state.draft.curve}
              disabled={cropMode || compareOpen}
              onChange={(curve) =>
                dispatch({
                  type: "draft-recipe",
                  recipe: withCurveSet(state.draft, curve),
                })
              }
              onCommit={requestCommit}
            />
          </div>
          <div className="mt-5">
            <HslPanel
              hsl={state.draft.hsl}
              disabled={cropMode || compareOpen}
              onChange={(band, key, value) =>
                dispatch({
                  type: "draft-recipe",
                  recipe: withHsl(state.draft, band, key, value),
                })
              }
              onResetBand={(band) => {
                dispatch({
                  type: "draft-recipe",
                  recipe: withHslSet(state.draft, {
                    ...normalizeHsl(state.draft.hsl),
                    [band]: {},
                  }),
                });
                requestCommit();
              }}
              onResetAll={() => {
                dispatch({
                  type: "draft-recipe",
                  recipe: withHslSet(state.draft, {}),
                });
                requestCommit();
              }}
              onCommit={requestCommit}
            />
          </div>
          <div className="mt-5">
            <ColorGradingPanel
              grading={state.draft.colorGrading}
              disabled={cropMode || compareOpen}
              onChange={(zone, key, value) =>
                dispatch({
                  type: "draft-recipe",
                  recipe: withColorGradeZone(state.draft, zone, key, value),
                })
              }
              onOptionChange={(key, value) => {
                dispatch({
                  type: "draft-recipe",
                  recipe: withColorGradingSet(state.draft, {
                    ...normalizeColorGrading(state.draft.colorGrading),
                    [key]: value,
                  }),
                });
              }}
              onResetZone={(zone) => {
                dispatch({
                  type: "draft-recipe",
                  recipe: withColorGradingSet(state.draft, {
                    ...normalizeColorGrading(state.draft.colorGrading),
                    [zone]: { hue: 0, saturation: 0 },
                  }),
                });
                requestCommit();
              }}
              onResetAll={() => {
                dispatch({
                  type: "draft-recipe",
                  recipe: withColorGradingSet(state.draft, {}),
                });
                requestCommit();
              }}
              onCommit={requestCommit}
            />
          </div>
          <div className="mt-5">
            <LocalAdjustmentsPanel
              recipe={state.draft}
              previewUrl={preview.url}
              previewWidth={preview.width}
              previewHeight={preview.height}
              sourceSize={
                image ? { width: image.width, height: image.height } : null
              }
              renderWarnings={preview.warnings}
              disabled={cropMode || compareOpen}
              layersEnabled={layersEnabled}
              semanticMasks={semanticMasks}
              onRequestSemanticMask={
                state.imageId
                  ? (kind) => createSemanticMask(state.imageId!, kind)
                  : undefined
              }
              onUseSemanticForGenerative={
                state.sessionId ? handleUseSemanticForGenerative : undefined
              }
              generativeMaskBlockedReason={
                state.baseGeneratedAssetId === null
                  ? null
                  : "当前基准是已生成的画面，AI 语义蒙版只能绑定原图；请在工作台手动绘制蒙版。"
              }
              onChange={(recipe) => dispatch({ type: "draft-recipe", recipe })}
              onCommit={requestCommit}
            />
          </div>
        </div>
      </aside>

      <PreviewMonitor
        preview={preview}
        visible={monitorVisible}
        onReturn={handleReturnToPreview}
      />

      <ExportDialog
        open={exportOpen}
        onClose={handleCloseExport}
        state={exporter.state}
        dirty={dirty}
        disabled={!canExport}
        onExport={handleExport}
        onCancel={() => void exporter.cancel()}
      />

      <DeletePhotoDialog
        open={deleteOpen}
        busy={deleting}
        error={deleteError}
        imageId={state.imageId}
        onCancel={() => {
          if (!deleting) {
            setDeleteOpen(false);
          }
        }}
        onConfirm={() => void handleConfirmDelete()}
      />
    </div>
  );
}

function EditorWorkspaceInner() {
  const apiStatus = useApiHealth();
  const runtime = useRuntimeLimits();
  const limits = runtime.limits;
  const state = useEditorState();
  const dispatch = useEditorDispatch();
  const [image, setImage] = useState<UploadedImage | null>(null);
  const [error, setError] = useState<UploadError | null>(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [deleteNotice, setDeleteNotice] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const { startSession } = useSessionActions();

  useSessionRestore();

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const handleFileSelected = useCallback(
    async (file: File) => {
      setDeleteNotice(null);
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
    pendingFile !== null &&
    error !== null &&
    !NON_RETRYABLE_CODES.has(error.code);

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
    setDeleteNotice(null);
    clearSessionUrl();
    dispatch({ type: "reset-editor" });
  }, [dispatch]);

  const handlePhotoDeleted = useCallback(() => {
    handleStartOver();
    setDeleteNotice("照片及其编辑会话、分析与缓存副本已从本机永久删除。");
  }, [handleStartOver]);

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
              <h2
                id="workspace-heading"
                className="text-sm font-medium tracking-tight text-white"
              >
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
          {deleteNotice && (
            <p
              role="status"
              className="mb-3 rounded-xl border border-accent/25 bg-accent/[0.06] px-3 py-2 text-xs text-accent"
            >
              {deleteNotice}
            </p>
          )}

          {error && (
            <ErrorAlert
              error={error}
              stage="上传图片"
              retryLabel="重试上传"
              onRetry={
                canRetry && pendingFile
                  ? () => void handleFileSelected(pendingFile)
                  : undefined
              }
              onDismiss={() => setError(null)}
            />
          )}

          {!inEditor && state.error && (
            <ErrorAlert
              error={state.error}
              stage={image ? "创建编辑会话" : undefined}
              retryLabel="重试创建会话"
              onRetry={
                image ? () => void startSession(image.imageId) : undefined
              }
              onDismiss={() => dispatch({ type: "error-cleared" })}
            />
          )}

          {inEditor ? (
            <EditorStage
              image={image}
              uploading={uploading}
              layersEnabled={runtime.layersEnabled}
              semanticMasks={runtime.semanticMasks}
              onFileSelected={handleFileSelected}
              onPhotoDeleted={handlePhotoDeleted}
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
            导出移除 EXIF/GPS 并嵌入 sRGB；AI 摄影分析只在你主动开启时运行。
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
