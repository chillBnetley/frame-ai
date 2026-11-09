"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useAnalysis } from "@/features/analysis/hooks/use-analysis";
import { uploadImage } from "@/lib/api/client";
import { acceptPlan, createPlan } from "@/lib/api/photographer";
import {
  activateRevision,
  createSession,
  getSession,
  listRevisions,
  redoSession,
  renderPreview,
  undoSession,
} from "@/lib/api/sessions";
import {
  fetchConversionModes,
  fetchStyleDetail,
  fetchStyleFit,
  fetchStyleLibrary,
} from "@/lib/api/style-library";
import { describeEditorError } from "@/lib/error-messages";
import { validateUploadFile } from "@/lib/upload-validation";
import type { PhotographerPlanResponse } from "@/types/photographer";
import type { EditRecipe, RevisionSummary, SessionState } from "@/types/session";
import type {
  ConversionMode,
  ConversionModeInfo,
  StyleDetailResponse,
  StyleFitResponse,
  StyleLibraryItem,
} from "@/types/style-library";

export type WorkspaceSaveState = "idle" | "saving" | "saved";

export interface MasterVisionWorkspaceState {
  styles: StyleLibraryItem[];
  stylesLoading: boolean;
  stylesError: string | null;
  styleId: string;
  style: StyleLibraryItem | null;
  detail: StyleDetailResponse | null;
  detailLoading: boolean;
  selectStyle: (styleId: string) => void;

  conversionModes: ConversionModeInfo[];
  conversionModesError: string | null;

  imageId: string | null;
  sessionId: string | null;
  session: SessionState | null;
  uploading: boolean;
  uploadError: string | null;
  upload: (file: File) => Promise<void>;

  analysis: ReturnType<typeof useAnalysis>;

  fit: StyleFitResponse | null;
  fitLoading: boolean;
  fitError: string | null;

  mode: ConversionMode;
  setMode: (mode: ConversionMode) => void;
  strength: number;
  setStrength: (strength: number) => void;

  plan: PhotographerPlanResponse | null;
  planLoading: boolean;
  planError: string | null;
  planStale: boolean;
  generate: () => Promise<void>;

  originalUrl: string | null;
  baselineLabel: string;
  resultUrl: string | null;
  renderLoading: boolean;
  renderError: string | null;
  retryRender: () => Promise<void>;
  handleImageError: () => void;

  saveState: WorkspaceSaveState;
  saveError: string | null;
  save: () => Promise<void>;
  resetSave: () => void;

  revisions: RevisionSummary[];
  historyLoading: boolean;
  historyError: string | null;
  historyBusy: string | null;
  reloadHistory: () => void;
  undo: () => Promise<void>;
  redo: () => Promise<void>;
  activate: (revisionId: string) => Promise<void>;
}

function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `mv-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function previewKeyFromUrl(url: string | null): string | null {
  if (!url) return null;
  const match = /\/api\/v1\/previews\/([0-9a-f]{64})$/i.exec(url);
  return match?.[1]?.toLowerCase() ?? null;
}

function messageFor(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallback;
}

function syncWorkspaceUrl(sessionId: string | null, styleId: string): void {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (sessionId) {
    url.searchParams.set("session", sessionId);
  } else {
    url.searchParams.delete("session");
  }
  if (styleId) {
    url.searchParams.set("style", styleId);
  }
  window.history.replaceState(window.history.state, "", url);
}

export function useMasterVisionWorkspace(
  initialStyleId: string,
  initialSessionId = "",
): MasterVisionWorkspaceState {
  const [styles, setStyles] = useState<StyleLibraryItem[]>([]);
  const [stylesLoading, setStylesLoading] = useState(true);
  const [stylesError, setStylesError] = useState<string | null>(null);
  const [styleId, setStyleId] = useState(initialStyleId);
  const [detail, setDetail] = useState<StyleDetailResponse | null>(null);
  const [detailKey, setDetailKey] = useState<string | null>(null);

  const [conversionModes, setConversionModes] = useState<ConversionModeInfo[]>([]);
  const [conversionModesError, setConversionModesError] = useState<string | null>(null);

  const [imageId, setImageId] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [session, setSession] = useState<SessionState | null>(null);
  const [baseRecipe, setBaseRecipe] = useState<EditRecipe | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const analysis = useAnalysis(imageId);
  const startAnalysis = analysis.start;

  const [fit, setFit] = useState<StyleFitResponse | null>(null);
  const [fitKey, setFitKey] = useState<string | null>(null);
  const [fitError, setFitError] = useState<string | null>(null);
  const [fitErrorKey, setFitErrorKey] = useState<string | null>(null);
  const [mode, setModeState] = useState<ConversionMode>("style");
  const [strength, setStrengthState] = useState(60);
  const touchedRef = useRef(false);

  const [plan, setPlan] = useState<PhotographerPlanResponse | null>(null);
  const [planLoading, setPlanLoading] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);
  const [plannedKey, setPlannedKey] = useState<string | null>(null);

  const [originalUrl, setOriginalUrl] = useState<string | null>(null);
  const [baselineLabel, setBaselineLabel] = useState("原图");
  const [resultUrl, setResultUrl] = useState<string | null>(null);
  const [renderLoading, setRenderLoading] = useState(false);
  const [renderError, setRenderError] = useState<string | null>(null);

  const [saveState, setSaveState] = useState<WorkspaceSaveState>("idle");
  const [saveError, setSaveError] = useState<string | null>(null);

  const [revisions, setRevisions] = useState<RevisionSummary[]>([]);
  const [historyLoadedKey, setHistoryLoadedKey] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyErrorKey, setHistoryErrorKey] = useState<string | null>(null);
  const [historyVersion, setHistoryVersion] = useState(0);
  const [historyBusy, setHistoryBusy] = useState<string | null>(null);

  const fitRequestRef = useRef<AbortController | null>(null);
  const planRequestRef = useRef<AbortController | null>(null);
  const renderRequestRef = useRef<AbortController | null>(null);
  const idempotencyKeyRef = useRef<string | null>(null);

  const style = styles.find((item) => item.id === styleId) ?? null;
  const currentKey = `${styleId}:${mode}:${strength}`;
  const planStale = plan !== null && plannedKey !== currentKey;
  const fitRequestKey = `${styleId}:${analysis.report?.analysisId ?? ""}`;
  const currentFit = fitKey === fitRequestKey ? fit : null;
  const currentFitError = fitErrorKey === fitRequestKey ? fitError : null;
  const fitLoading =
    analysis.report !== null &&
    styleId !== "" &&
    fitKey !== fitRequestKey &&
    fitErrorKey !== fitRequestKey;
  const historyKey = `${sessionId ?? ""}:${historyVersion}`;
  const currentRevisions = historyLoadedKey === historyKey ? revisions : [];
  const currentHistoryError = historyErrorKey === historyKey ? historyError : null;
  const historyLoading =
    sessionId !== null &&
    historyLoadedKey !== historyKey &&
    historyErrorKey !== historyKey;

  useEffect(() => {
    if (!initialSessionId) return;
    const controller = new AbortController();
    getSession(initialSessionId, controller.signal)
      .then((state) => {
        if (controller.signal.aborted) return;
        const creation = state.revision.creation;
        setImageId(state.imageId);
        setSessionId(state.sessionId);
        setSession(state);
        setBaseRecipe(state.revision.recipe);
        setBaselineLabel(state.revision.source === "initial" ? "原图" : "恢复时的版本");
        if (creation?.styleId) setStyleId(creation.styleId);
        if (creation?.conversionMode) {
          touchedRef.current = true;
          setModeState(creation.conversionMode);
        }
        if (creation?.styleStrength != null) {
          touchedRef.current = true;
          setStrengthState(Math.round(creation.styleStrength * 100));
        }
        syncWorkspaceUrl(state.sessionId, creation?.styleId ?? initialStyleId);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setUploadError(messageFor(error, "无法恢复上次的编辑会话。"));
        }
      });
    return () => controller.abort();
  }, [initialSessionId, initialStyleId]);

  useEffect(() => {
    const controller = new AbortController();
    fetchStyleLibrary({}, controller.signal)
      .then((response) => {
        if (controller.signal.aborted) return;
        setStyles(response.styles);
        setStylesLoading(false);
        setStylesError(null);
        setStyleId((current) => {
          if (response.styles.some((item) => item.id === current)) return current;
          return response.styles[0]?.id ?? "";
        });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setStylesError(messageFor(error, "无法加载风格库，请确认 API 服务已启动。"));
          setStylesLoading(false);
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    fetchConversionModes(controller.signal)
      .then((response) => {
        if (!controller.signal.aborted) setConversionModes(response.modes);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setConversionModesError(messageFor(error, "无法加载转换模式。"));
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (styleId === "") {
      return;
    }
    const controller = new AbortController();
    fetchStyleDetail(styleId, controller.signal)
      .then((response) => {
        if (!controller.signal.aborted) {
          setDetail(response);
          setDetailKey(styleId);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setDetail(null);
          setDetailKey(styleId);
        }
      });
    return () => controller.abort();
  }, [styleId]);

  const currentDetail = detailKey === styleId ? detail : null;
  const detailLoading = styleId !== "" && detailKey !== styleId;

  useEffect(() => {
    if (!imageId) return;
    startAnalysis();
  }, [imageId, startAnalysis]);

  useEffect(() => {
    const report = analysis.report;
    if (!report || !styleId) return;
    fitRequestRef.current?.abort();
    const controller = new AbortController();
    fitRequestRef.current = controller;
    const requestKey = `${styleId}:${report.analysisId}`;
    fetchStyleFit(styleId, String(report.image.id), controller.signal)
      .then((response) => {
        if (controller.signal.aborted) return;
        setFit(response);
        setFitKey(requestKey);
        setFitError(null);
        setFitErrorKey(null);
        if (!touchedRef.current) {
          setModeState(response.recommendedMode);
          setStrengthState(Math.round(response.recommendedStrength.default * 100));
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setFitError(messageFor(error, "适配度分析失败，请重试。"));
          setFitErrorKey(requestKey);
          setFit(null);
          setFitKey(null);
        }
      });
    return () => controller.abort();
  }, [analysis.report, styleId]);

  useEffect(() => {
    if (!sessionId || !baseRecipe) return;
    renderRequestRef.current?.abort();
    const controller = new AbortController();
    renderRequestRef.current = controller;
    renderPreview(
      sessionId,
      { recipe: baseRecipe, quality: "final" },
      controller.signal,
    )
      .then((response) => {
        if (!controller.signal.aborted) setOriginalUrl(response.previewUrl);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setRenderError(describeEditorError(error).message);
        }
      });
    return () => controller.abort();
  }, [baseRecipe, sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    const controller = new AbortController();
    const requestKey = `${sessionId}:${historyVersion}`;
    listRevisions(sessionId, { limit: 40 }, controller.signal)
      .then((response) => {
        if (!controller.signal.aborted) {
          setRevisions(response.items);
          setHistoryLoadedKey(requestKey);
          setHistoryError(null);
          setHistoryErrorKey(null);
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setHistoryError(messageFor(error, "编辑历史加载失败，请重试。"));
          setHistoryErrorKey(requestKey);
          setRevisions([]);
          setHistoryLoadedKey(null);
        }
      });
    return () => controller.abort();
    // historyVersion deliberately re-runs after a save, undo, redo, or restore.
  }, [historyVersion, sessionId]);

  const selectStyle = useCallback((nextStyleId: string) => {
    if (nextStyleId === styleId) return;
    fitRequestRef.current?.abort();
    planRequestRef.current?.abort();
    renderRequestRef.current?.abort();
    touchedRef.current = false;
    setStyleId(nextStyleId);
    setFit(null);
    setFitKey(null);
    setFitError(null);
    setFitErrorKey(null);
    setPlan(null);
    setPlanError(null);
    setPlanLoading(false);
    setResultUrl(null);
    setRenderError(null);
    setRenderLoading(false);
    setPlannedKey(null);
    setSaveState("idle");
    setSaveError(null);
    idempotencyKeyRef.current = null;
    syncWorkspaceUrl(sessionId, nextStyleId);
  }, [sessionId, styleId]);

  const setMode = useCallback((nextMode: ConversionMode) => {
    touchedRef.current = true;
    setModeState(nextMode);
  }, []);

  const setStrength = useCallback((nextStrength: number) => {
    touchedRef.current = true;
    setStrengthState(Math.min(100, Math.max(0, nextStrength)));
  }, []);

  const upload = useCallback(async (file: File) => {
    const validation = validateUploadFile(file);
    if (!validation.ok) {
      setUploadError(validation.message);
      return;
    }
    fitRequestRef.current?.abort();
    planRequestRef.current?.abort();
    renderRequestRef.current?.abort();
    setUploading(true);
    setUploadError(null);
    try {
      const uploaded = await uploadImage(file);
      const created = await createSession(uploaded.imageId);
      setImageId(uploaded.imageId);
      setSessionId(created.sessionId);
      setSession(created);
      setBaseRecipe(created.revision.recipe);
      setBaselineLabel("原图");
      syncWorkspaceUrl(created.sessionId, styleId);
      setOriginalUrl(null);
      setResultUrl(null);
      setPlan(null);
      setPlannedKey(null);
      setPlanError(null);
      setRenderError(null);
      setSaveState("idle");
      setSaveError(null);
      idempotencyKeyRef.current = null;
      setFit(null);
      setFitError(null);
      touchedRef.current = false;
    } catch (error) {
      setUploadError(describeEditorError(error).message);
    } finally {
      setUploading(false);
    }
  }, [styleId]);

  const generate = useCallback(async () => {
    if (!sessionId || !session || !analysis.analysisId || !styleId) {
      setPlanError("请先上传照片并等待分析完成。");
      return;
    }
    planRequestRef.current?.abort();
    const controller = new AbortController();
    planRequestRef.current = controller;
    touchedRef.current = true;
    setPlanLoading(true);
    setPlanError(null);
    setSaveState("idle");
    setSaveError(null);
    try {
      const response = await createPlan(
        {
          sessionId,
          analysisId: analysis.analysisId,
          mode: "style",
          styleId,
          styleStrength: strength / 100,
          conversionMode: mode,
        },
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setPlan(response);
      setPlannedKey(`${styleId}:${mode}:${strength}`);
      idempotencyKeyRef.current = newIdempotencyKey();
      setPlanLoading(false);

      renderRequestRef.current?.abort();
      const renderController = new AbortController();
      renderRequestRef.current = renderController;
      setRenderLoading(true);
      setRenderError(null);
      try {
        const rendered = await renderPreview(
          sessionId,
          { recipe: response.recipe, quality: "draft" },
          renderController.signal,
        );
        if (!renderController.signal.aborted) {
          setResultUrl(rendered.previewUrl);
        }
      } catch (error) {
        if (!renderController.signal.aborted) {
          setRenderError(describeEditorError(error).message);
        }
      } finally {
        if (!renderController.signal.aborted) setRenderLoading(false);
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setPlanError(describeEditorError(error).message);
        setPlanLoading(false);
      }
    }
  }, [analysis.analysisId, mode, session, sessionId, strength, styleId]);

  const retryRender = useCallback(async () => {
    if (!sessionId || !plan) return;
    setRenderLoading(true);
    setRenderError(null);
    try {
      const rendered = await renderPreview(sessionId, { recipe: plan.recipe, quality: "draft" });
      setResultUrl(rendered.previewUrl);
    } catch (error) {
      setRenderError(describeEditorError(error).message);
    } finally {
      setRenderLoading(false);
    }
  }, [plan, sessionId]);

  const handleImageError = useCallback(() => {
    setRenderError("预览图片加载失败，请重试渲染或检查网络连接。");
  }, []);

  const resetGenerated = useCallback(() => {
    planRequestRef.current?.abort();
    renderRequestRef.current?.abort();
    setPlan(null);
    setPlanLoading(false);
    setPlanError(null);
    setResultUrl(null);
    setRenderError(null);
    setRenderLoading(false);
    setPlannedKey(null);
    setSaveState("idle");
    setSaveError(null);
    idempotencyKeyRef.current = null;
  }, []);

  const save = useCallback(async () => {
    if (!sessionId || !session || !plan) return;
    const renderKey = previewKeyFromUrl(resultUrl);
    if (renderKey === null) {
      setSaveError("请等待真实预览渲染完成后再保存。");
      return;
    }
    setSaveState("saving");
    setSaveError(null);
    try {
      const key = idempotencyKeyRef.current ?? newIdempotencyKey();
      idempotencyKeyRef.current = key;
      const state = await acceptPlan(
        plan.planId,
        {
          parentRevisionId: session.activeRevisionId,
          renderKey,
        },
        key,
      );
      setSession(state);
      setSaveState("saved");
      setHistoryVersion((value) => value + 1);
    } catch (error) {
      setSaveState("idle");
      setSaveError(describeEditorError(error).message);
    }
  }, [plan, resultUrl, session, sessionId]);

  const undo = useCallback(async () => {
    if (!sessionId) return;
    setHistoryBusy("undo");
    setHistoryError(null);
    try {
      const state = await undoSession(sessionId);
      setSession(state);
      resetGenerated();
      setHistoryVersion((value) => value + 1);
    } catch (error) {
      setHistoryError(describeEditorError(error).message);
      setHistoryErrorKey(historyKey);
    } finally {
      setHistoryBusy(null);
    }
  }, [historyKey, resetGenerated, sessionId]);

  const redo = useCallback(async () => {
    if (!sessionId) return;
    setHistoryBusy("redo");
    setHistoryError(null);
    try {
      const state = await redoSession(sessionId);
      setSession(state);
      resetGenerated();
      setHistoryVersion((value) => value + 1);
    } catch (error) {
      setHistoryError(describeEditorError(error).message);
      setHistoryErrorKey(historyKey);
    } finally {
      setHistoryBusy(null);
    }
  }, [historyKey, resetGenerated, sessionId]);

  const activate = useCallback(
    async (revisionId: string) => {
      if (!sessionId) return;
      setHistoryBusy(revisionId);
      setHistoryError(null);
      try {
        const state = await activateRevision(sessionId, revisionId);
        setSession(state);
        resetGenerated();
        setHistoryVersion((value) => value + 1);
      } catch (error) {
        setHistoryError(describeEditorError(error).message);
        setHistoryErrorKey(historyKey);
      } finally {
        setHistoryBusy(null);
      }
    },
    [historyKey, resetGenerated, sessionId],
  );

  const reloadHistory = useCallback(() => {
    setHistoryVersion((value) => value + 1);
  }, []);

  const resetSave = useCallback(() => {
    setSaveState("idle");
    setSaveError(null);
  }, []);

  return {
    styles,
    stylesLoading,
    stylesError,
    styleId,
    style,
    detail: currentDetail,
    detailLoading,
    selectStyle,
    conversionModes,
    conversionModesError,
    imageId,
    sessionId,
    session,
    uploading,
    uploadError,
    upload,
    analysis,
    fit: currentFit,
    fitLoading,
    fitError: currentFitError,
    mode,
    setMode,
    strength,
    setStrength,
    plan,
    planLoading,
    planError,
    planStale,
    generate,
    originalUrl,
    baselineLabel,
    resultUrl,
    renderLoading,
    renderError,
    retryRender,
    handleImageError,
    saveState,
    saveError,
    save,
    resetSave,
    revisions: currentRevisions,
    historyLoading,
    historyError: currentHistoryError,
    historyBusy,
    reloadHistory,
    undo,
    redo,
    activate,
  };
}
