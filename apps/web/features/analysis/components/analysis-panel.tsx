"use client";

import { RefreshIcon } from "@/components/icons";
import type { UseAnalysisResult } from "@/features/analysis/hooks/use-analysis";
import { describeAnalysisStage } from "@/features/analysis/presentation";
import type { AnalysisReport } from "@/types/analysis";

import { AnalysisReportView } from "./analysis-report";

const primaryButton =
  "inline-flex min-h-11 items-center gap-2 rounded-lg bg-accent px-4 text-xs font-semibold text-[#101208] transition-colors hover:bg-accent/85 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-40";
const secondaryButton =
  "inline-flex min-h-11 items-center gap-2 rounded-lg border border-white/12 bg-white/[0.03] px-3 text-xs text-white/65 transition-colors hover:bg-white/[0.07] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

export interface AnalysisPanelProps {
  open: boolean;
  imageId: string;
  analysis: UseAnalysisResult;
  onClose: () => void;
  className?: string;
}

function reportForImage(
  report: AnalysisReport | null,
  imageId: string,
): AnalysisReport | null {
  if (!report || report.image.id !== imageId) {
    return null;
  }
  return report;
}

export function AnalysisPanel({
  open,
  imageId,
  analysis,
  onClose,
  className,
}: AnalysisPanelProps) {
  if (!open) {
    return null;
  }

  const report = reportForImage(analysis.report, imageId);
  const isMock = analysis.isMock || report?.engine.isMock === true;
  const running = analysis.running;
  const statusLabel = describeAnalysisStage(analysis.status, analysis.stage);
  const idle = analysis.status === null && !analysis.requestPending;
  const failed = analysis.status === "failed";

  return (
    <section
      id="analysis-panel"
      aria-labelledby="analysis-panel-title"
      className={`analysis-panel min-w-0 rounded-2xl border border-white/8 bg-black/20 xl:sticky xl:top-[calc(var(--app-header-height)+1rem)] xl:max-h-[calc(100dvh-var(--app-header-height)-2rem)] xl:self-start xl:overflow-y-auto xl:overscroll-contain ${className ?? ""}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-white/8 px-4 py-3">
        <div>
          <h3 id="analysis-panel-title" className="text-sm font-medium text-white">
            AI 摄影分析
          </h3>
          <p className="mt-0.5 text-[11px] text-white/40">
            只读取原图并生成诊断，不会修改照片。
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="关闭 AI 摄影分析"
          className="grid size-11 place-items-center rounded-lg text-white/45 transition-colors hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          <span aria-hidden="true">✕</span>
        </button>
      </div>

      <div className="grid gap-3 p-4">
        {isMock && (
          <p className="rounded-lg border border-amber-300/25 bg-amber-300/10 px-3 py-2 text-[11px] text-amber-950">
            模拟分析（未调用真实视觉模型）
          </p>
        )}

        <div className="flex flex-wrap items-center justify-between gap-2">
          <p
            role="status"
            aria-live="polite"
            className="inline-flex items-center gap-2 text-[11px] text-white/55"
          >
            <span
              aria-hidden="true"
              className={`size-1.5 rounded-full ${
                running
                  ? "animate-pulse bg-accent"
                  : failed
                    ? "bg-red-400"
                    : report
                      ? "bg-emerald-400"
                      : "bg-white/30"
              }`}
            />
            {statusLabel}
          </p>
          {!running && report && (
            <button
              type="button"
              onClick={analysis.rerun}
              className={secondaryButton}
            >
              重新分析
            </button>
          )}
        </div>

        {analysis.error && (
          <div
            role="alert"
            className="rounded-lg border border-red-300/25 bg-red-300/[0.06] px-3 py-2 text-[11px] text-red-200"
          >
            <p>{analysis.error.message}</p>
            <p className="mt-1 font-mono text-[10px] text-red-200/70">
              {analysis.error.code}
              {analysis.error.requestId
                ? ` · 请求 ID ${analysis.error.requestId}`
                : ""}
            </p>
            {failed && (
              <button
                type="button"
                onClick={analysis.retry}
                className="mt-2 inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-red-300/25 bg-red-300/10 px-3 text-xs text-red-100 transition-colors hover:bg-red-300/20 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                <RefreshIcon className="size-3.5" />
                重试
              </button>
            )}
          </div>
        )}

        {idle && (
          <div className="grid gap-2 rounded-xl border border-white/8 bg-white/[0.02] p-3">
            <p className="text-[11px] leading-relaxed text-white/55">
              识别场景与主体，分析光线和色彩，生成可执行的摄影建议。分析在后台运行，不会阻塞现有编辑与导出。
            </p>
            <button
              type="button"
              onClick={() => analysis.start(false)}
              className={`${primaryButton} justify-center`}
            >
              开始分析
            </button>
          </div>
        )}

        {running && !report && (
          <div className="rounded-xl border border-white/8 bg-white/[0.02] p-3">
            <p className="text-[11px] text-white/50">
              正在分析照片，阶段完成前不会显示虚假进度。通常需要几秒到几十秒。
            </p>
          </div>
        )}

        {running && report && (
          <p className="rounded-lg border border-white/8 bg-white/[0.02] px-3 py-2 text-[11px] text-white/45">
            正在重新分析，当前显示上一次结果，完成后自动替换。
          </p>
        )}

        {!analysis.error && analysis.status === "completed" && !report && (
          <p className="rounded-lg border border-amber-300/20 bg-amber-300/[0.05] px-3 py-2 text-[11px] text-amber-950">
            分析已完成，但结果暂时不可用。
          </p>
        )}

        {report && (
          <AnalysisReportView
            key={report.analysisId}
            imageId={imageId}
            report={report}
          />
        )}

        {!idle && !report && !running && !analysis.error && (
          <p className="text-[11px] text-white/40">等待分析结果。</p>
        )}
      </div>
    </section>
  );
}
