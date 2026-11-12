"use client";

import { useCallback, useId, useMemo, useRef, type ReactNode } from "react";

import { GenerativeTaskStatus } from "../components/generative-task-status";
import { buildGenerativeSuggestions, type GenerativeSuggestion } from "../suggestions";
import { StudioCanvas } from "./studio-canvas";
import { StudioError } from "./studio-error";
import { StudioTaskPanel } from "./studio-task-panel";
import { StudioToolRail } from "./studio-tool-rail";
import { CANVAS_ZOOM_STEP } from "@/lib/generative-canvas";
import { useCreativeStudio, type CreativeStudioController } from "./use-creative-studio";
import type { StudioCapability } from "./use-studio-state";
import type { AnalysisReport } from "@/types/analysis";
import type { SessionState } from "@/types/session";

export interface CreativeStudioProps {
  sessionId: string;
  previewImageUrl?: string | null;
  /** Base asset dimensions; the preview is downscaled and must not drive geometry. */
  baseWidth: number;
  baseHeight: number;
  /** False when the committed recipe carries crop or rotation. */
  gradedBaseAvailable: boolean;
  originalImageUrl?: string | null;
  analysisReport?: AnalysisReport | null;
  initialMaskId?: string | null;
  initialCapability?: StudioCapability;
  /** False when the base is a generated asset, so analysis bboxes no longer line up. */
  subjectMaskAvailable?: boolean;
  onResultAccepted?: (state: SessionState) => void;
  onResultRejected?: () => void;
  onExit?: () => void;
  historySlot?: ReactNode;
}

const CANVAS_HEIGHT_CLASS =
  "h-[46vh] min-h-64 lg:h-[52vh] xl:h-auto xl:min-h-0 xl:flex-1";

export function CreativeStudio({
  sessionId,
  previewImageUrl = null,
  baseWidth,
  baseHeight,
  gradedBaseAvailable,
  originalImageUrl = null,
  analysisReport = null,
  initialMaskId = null,
  initialCapability,
  subjectMaskAvailable = false,
  onResultAccepted,
  onResultRejected,
  onExit,
  historySlot,
}: CreativeStudioProps) {
  const headingId = useId();
  const controller = useCreativeStudio({
    sessionId,
    baseWidth,
    baseHeight,
    gradedBaseAvailable,
    initialMaskId,
    initialCapability,
    subjectMaskAvailable,
    onResultAccepted,
    onResultRejected,
  });
  const suggestions = useMemo(
    () => buildGenerativeSuggestions(analysisReport),
    [analysisReport],
  );

  return (
    <StudioShell
      controller={controller}
      sessionId={sessionId}
      previewImageUrl={previewImageUrl}
      originalImageUrl={originalImageUrl}
      suggestions={suggestions}
      onExit={onExit}
      historySlot={historySlot}
      headingId={headingId}
    />
  );
}

interface StudioShellProps {
  controller: CreativeStudioController;
  sessionId: string;
  previewImageUrl: string | null;
  originalImageUrl: string | null;
  suggestions: GenerativeSuggestion[];
  onExit?: () => void;
  historySlot?: ReactNode;
  headingId: string;
}

function StudioShell({
  controller,
  sessionId,
  previewImageUrl,
  originalImageUrl,
  suggestions,
  onExit,
  historySlot,
  headingId,
}: StudioShellProps) {
  const {
    studio,
    capability,
    task,
    geometry,
    capabilities,
    maskImageUrl,
    stageLabels,
    baseWidth,
    baseHeight,
  } = controller;
  const state = studio.state;
  const viewportRef = useRef<{ width: number; height: number } | null>(null);

  const expanded = capability === "outpaint" && geometry.isExpanded;
  const frameWidth = expanded ? geometry.targetWidth : baseWidth;
  const frameHeight = expanded ? geometry.targetHeight : baseHeight;
  const result = task.candidates[0] ?? null;
  const hasResult = result !== null;

  const rememberViewport = useCallback((width: number, height: number): void => {
    viewportRef.current = { width, height };
  }, []);

  const fitToWindow = useCallback((): void => {
    const box = viewportRef.current;
    if (box) {
      studio.fitTo(box.width, box.height, frameWidth, frameHeight);
    }
  }, [frameHeight, frameWidth, studio]);

  const outpaintGeometry = capability === "outpaint" && geometry.isExpanded ? geometry : null;

  return (
    <section
      id="creative-studio"
      aria-labelledby={headingId}
      className="flex flex-col gap-4 rounded-[28px] border border-[#e4e8e5] bg-[#ffffff] p-3 text-[#202522] shadow-[0_18px_50px_-32px_rgba(24,50,38,0.22)] sm:p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id={headingId} className="text-sm font-medium text-[#202522]">
            AI 创意工作台
          </h2>
          <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.14em] text-[#8a938e]">
            Session {sessionId.slice(0, 8)} · 生成结果采纳后写入同一条版本线
          </p>
        </div>
        {onExit && (
          <button
            type="button"
            onClick={onExit}
            className="min-h-11 rounded-xl border border-[#dfe4e0] bg-[#f6f7f6] px-3 text-xs text-[#3d4541] transition-colors hover:border-[#c9d2cd] hover:bg-[#eef1ef] hover:text-[#202522] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#277a68]"
          >
            返回参数精修
          </button>
        )}
      </div>

      <div className="flex min-h-0 flex-col gap-3 xl:h-[calc(100dvh-15rem)] xl:min-h-[560px]">
        <StudioToolRail
          capability={capability}
          capabilities={capabilities}
          onCapabilityChange={studio.setCapability}
          baseLayer={state.baseLayer}
          onBaseLayerChange={studio.setBaseLayer}
          resultVisible={state.resultVisible}
          onResultVisibleChange={studio.setResultVisible}
          maskOverlayVisible={state.maskOverlayVisible}
          onToggleMaskOverlay={studio.toggleMaskOverlay}
          maskRequired={capability !== "outpaint"}
          compare={state.compare}
          onCompareChange={studio.setCompare}
          hasResult={hasResult}
          scale={state.view.scale}
          onZoomIn={() => studio.zoomBy(CANVAS_ZOOM_STEP, 0, 0)}
          onZoomOut={() => studio.zoomBy(1 / CANVAS_ZOOM_STEP, 0, 0)}
          onFitToWindow={fitToWindow}
          onResetScale={studio.resetView}
          disabled={task.isRunning}
        />

        <div className="grid min-w-0 gap-4 xl:min-h-0 xl:flex-1 xl:grid-cols-[minmax(0,1fr)_minmax(300px,340px)] xl:items-stretch">
          <div className="flex min-w-0 flex-col gap-3 xl:min-h-0">
            <div className={CANVAS_HEIGHT_CLASS}>
              <StudioCanvas
                baseImageUrl={previewImageUrl}
                originalImageUrl={originalImageUrl}
                result={result}
                baseLayer={state.baseLayer}
                resultVisible={state.resultVisible}
                maskOverlayVisible={state.maskOverlayVisible}
                maskImageUrl={maskImageUrl}
                outpaintGeometry={outpaintGeometry}
                baseWidth={baseWidth}
                baseHeight={baseHeight}
                view={state.view}
                compare={state.compare}
                comparePosition={state.comparePosition}
                isRunning={task.isRunning}
                stageLabel={task.stage ? stageLabels[task.stage] ?? null : null}
                onZoom={studio.zoomBy}
                onPan={studio.panBy}
                onFit={studio.fitTo}
                onComparePositionChange={studio.setComparePosition}
                onViewportSize={rememberViewport}
              />
            </div>

            {task.isRunning && task.stage && (
              <GenerativeTaskStatus
                stage={task.stage}
                labels={stageLabels}
                cancelLabel="取消任务"
                onCancel={() => void task.cancel()}
              />
            )}

            <StudioError error={task.errorInfo} />
          </div>

          <StudioTaskPanel
            controller={controller}
            sessionId={sessionId}
            imageUrl={previewImageUrl ?? originalImageUrl}
            baseWidth={baseWidth}
            baseHeight={baseHeight}
            suggestions={suggestions}
          />
        </div>
      </div>

      {historySlot && <div className="editor-history">{historySlot}</div>}
    </section>
  );
}
