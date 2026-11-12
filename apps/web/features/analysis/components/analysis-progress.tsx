"use client";

import { useEffect, useState } from "react";

import {
  ANALYSIS_STAGE_STEPS,
  analysisActiveStep,
  analysisElapsedSeconds,
  analysisSlowHint,
  formatAnalysisElapsed,
  isRunningStatus,
} from "@/features/analysis/presentation";
import type { TaskStage, TaskStatus } from "@/types/analysis";

type Tone = "dark" | "light";

const TONE_CLASSES: Record<
  Tone,
  {
    label: string;
    elapsed: string;
    done: string;
    active: string;
    pending: string;
    hint: string;
  }
> = {
  dark: {
    label: "text-white/55",
    elapsed: "text-white/35",
    done: "bg-accent",
    active: "bg-accent/50",
    pending: "bg-white/12",
    hint: "border-[#cfe3dc] bg-[#f1f7f4] text-[#33574c]",
  },
  light: {
    label: "text-[#68746e]",
    elapsed: "text-[#8a9690]",
    done: "bg-[#4c9b83]",
    active: "bg-[#4c9b83]/50",
    pending: "bg-[#e8eeea]",
    hint: "border-[#cfe3dc] bg-[#f1f7f4] text-[#33574c]",
  },
};

export interface AnalysisProgressProps {
  status: TaskStatus | null;
  stage: TaskStage | null;
  startedAt: number | null;
  tone?: Tone;
  className?: string;
}

/**
 * Advances one segment per stage reported by the API. There is no numeric
 * percentage because the model provider exposes no token-level progress.
 */
export function AnalysisProgress({
  status,
  stage,
  startedAt,
  tone = "dark",
  className,
}: AnalysisProgressProps) {
  const running = isRunningStatus(status);
  const [now, setNow] = useState(() => Date.now());
  const colors = TONE_CLASSES[tone];

  useEffect(() => {
    if (!running) {
      return;
    }
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [running]);

  const activeStep = analysisActiveStep(status, stage);
  const queued =
    running && (status === "pending" || stage === null || stage === "queued");
  const elapsed = analysisElapsedSeconds(startedAt, now);
  const hint = running ? analysisSlowHint(elapsed) : null;
  const label =
    status === "completed" || stage === "completed"
      ? "分析完成"
      : queued
        ? "等待分析"
        : `第 ${activeStep + 1}/${ANALYSIS_STAGE_STEPS.length} 步 · ${
            ANALYSIS_STAGE_STEPS[activeStep]?.label ?? "生成摄影诊断"
          }`;

  return (
    <div className={className}>
      <div
        role="progressbar"
        aria-label="分析阶段进度"
        aria-valuemin={0}
        aria-valuemax={ANALYSIS_STAGE_STEPS.length}
        aria-valuenow={activeStep}
        aria-valuetext={label}
        className="flex gap-1"
      >
        {ANALYSIS_STAGE_STEPS.map((step, index) => {
          const done = index < activeStep;
          const active = running && !queued && index === activeStep;
          return (
            <span
              key={step.stage}
              aria-hidden="true"
              className={`h-1.5 flex-1 rounded-full transition-colors duration-500 ${
                done
                  ? colors.done
                  : active
                    ? `animate-pulse ${colors.active}`
                    : queued && index === 0
                      ? `animate-pulse ${colors.active}`
                      : colors.pending
              }`}
            />
          );
        })}
      </div>
      <div className="mt-1.5 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-[11px]">
        <span className={colors.label}>{label}</span>
        {running && startedAt !== null && (
          <span className={`font-mono text-[10px] ${colors.elapsed}`}>
            已用 {formatAnalysisElapsed(elapsed)}
          </span>
        )}
      </div>
      {hint !== null && (
        <p
          className={`mt-2 rounded-lg border px-2.5 py-1.5 text-[11px] leading-relaxed ${colors.hint}`}
        >
          {hint}
        </p>
      )}
    </div>
  );
}
