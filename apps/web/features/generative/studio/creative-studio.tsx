"use client";

import { useCallback, useId, useRef, type ReactNode } from "react";

import { GenerativeTaskStatus } from "../components/generative-task-status";
import { StudioCanvas } from "./studio-canvas";
import { StudioError } from "./studio-error";
import { StudioTaskPanel } from "./studio-task-panel";
import { StudioToolRail } from "./studio-tool-rail";
import { CANVAS_ZOOM_STEP } from "@/lib/generative-canvas";
import { useCreativeStudio, type CreativeStudioController } from "./use-creative-studio";
import type { SessionState } from "@/types/session";

export interface CreativeStudioProps {
  sessionId: string;
  previewImageUrl?: string | null;
  previewWidth?: number;
  previewHeight?: number;
  originalImageUrl?: string | null;
  imageWidth?: number;
  imageHeight?: number;
  initialMaskId?: string | null;
  onResultAccepted?: (state: SessionState) => void;
  onResultRejected?: () => void;
  onExit?: () => void;
  historySlot?: ReactNode;
}

const CANVAS_HEIGHT_CLASS = "h-[46vh] min-h-64 lg:h-[58vh]";

export function CreativeStudio({
  sessionId,
  previewImageUrl = null,
  previewWidth = 0,
  previewHeight = 0,
  originalImageUrl = null,
  imageWidth = 0,
  imageHeight = 0,
  initialMaskId = null,
  onResultAccepted,
  onResultRejected,
  onExit,
  historySlot,
}: CreativeStudioProps) {
  const headingId = useId();
  const controller = useCreativeStudio({
    sessionId,
    baseWidth: previewWidth > 0 ? previewWidth : imageWidth || 1920,
    baseHeight: previewHeight > 0 ? previewHeight : imageHeight || 1080,
    initialMaskId,
    onResultAccepted,
    onResultRejected,
  });

  return (
    <StudioShell
      controller={controller}
      sessionId={sessionId}
      previewImageUrl={previewImageUrl}
      originalImageUrl={originalImageUrl}
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
  onExit?: () => void;
  historySlot?: ReactNode;
  headingId: string;
}

function StudioShell({
  controller,
  sessionId,
  previewImageUrl,
  originalImageUrl,
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
      className="flex flex-col gap-4 rounded-[28px] border border-white/10 bg-black/20 p-3 sm:p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id={headingId} className="text-sm font-medium text-white">
            AI 创意工作台
          </h2>
          <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.14em] text-white/30">
            Session {sessionId.slice(0, 8)} · 生成结果采纳后写入同一条版本线
          </p>
        </div>
        {onExit && (
          <button
            type="button"
            onClick={onExit}
            className="min-h-11 rounded-xl border border-white/12 bg-white/[0.03] px-3 text-xs text-white/70 transition-colors hover:bg-white/[0.07] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            返回参数精修
          </button>
        )}
      </div>

      <div className="grid min-w-0 gap-4 xl:grid-cols-[210px_minmax(0,1fr)_minmax(300px,340px)]">
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

        <div className="flex min-w-0 flex-col gap-3">
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
        />
      </div>

      {historySlot && <div className="editor-history">{historySlot}</div>}
    </section>
  );
}
