"use client";

import { useCallback, useEffect, useState } from "react";

import {
  createAnalysis,
  fetchAnalysisReport,
  fetchAnalysisStatus,
} from "@/lib/api/analysis";
import { ApiClientError } from "@/lib/api/client";
import { analysisFailureMessage } from "@/lib/error-messages";
import type {
  AnalysisReport,
  AnalysisStatusResponse,
  TaskStage,
  TaskStatus,
} from "@/types/analysis";

export const ANALYSIS_FAST_POLL_MS = 1_000;
export const ANALYSIS_SLOW_POLL_MS = 2_000;
export const ANALYSIS_FAST_POLL_WINDOW_MS = 10_000;

export interface AnalysisError {
  code: string;
  message: string;
  requestId: string | null;
}

export interface AnalysisState {
  analysisId: string | null;
  status: TaskStatus | null;
  stage: TaskStage | null;
  isMock: boolean;
  report: AnalysisReport | null;
  error: AnalysisError | null;
  requestPending: boolean;
}

export interface UseAnalysisResult extends AnalysisState {
  running: boolean;
  start: (force?: boolean) => void;
  retry: () => void;
  rerun: () => void;
}

const INITIAL_STATE: AnalysisState = {
  analysisId: null,
  status: null,
  stage: null,
  isMock: false,
  report: null,
  error: null,
  requestPending: false,
};

const MISMATCH_ERROR: AnalysisError = {
  code: "analysis_mismatch",
  message: "分析结果与当前图片不匹配，已忽略该结果。",
  requestId: null,
};

const UNAVAILABLE_ERROR: AnalysisError = {
  code: "analysis_unavailable",
  message: "分析已完成，但结果暂时不可用。",
  requestId: null,
};

const DEFAULT_FAILURE: AnalysisError = {
  code: "analysis_failed",
  message: "分析失败，请稍后重试。",
  requestId: null,
};

function toAnalysisError(error: unknown): AnalysisError {
  if (error instanceof ApiClientError) {
    return {
      code: error.code,
      message: analysisFailureMessage(error.code, error.message),
      requestId: error.requestId,
    };
  }
  return {
    code: "analysis_error",
    message: "分析请求失败，请确认 API 服务可用后重试。",
    requestId: null,
  };
}

function isTerminal(status: TaskStatus): boolean {
  return status === "completed" || status === "failed";
}

class AnalysisController {
  private state: AnalysisState = INITIAL_STATE;
  private imageId: string | null = null;
  private taskId: string | null = null;
  private generation = 0;
  private request: AbortController | null = null;
  private timer: ReturnType<typeof globalThis.setTimeout> | null = null;
  private startedAt = 0;
  private active = false;
  private paused = false;

  constructor(private readonly emit: (state: AnalysisState) => void) {}

  setImage(imageId: string | null): void {
    if (imageId === this.imageId) {
      return;
    }
    this.imageId = imageId;
    this.stop();
    this.state = INITIAL_STATE;
    this.emit(this.state);
  }

  start(force = false): void {
    const imageId = this.imageId;
    if (!imageId) {
      return;
    }
    const generation = ++this.generation;
    this.active = true;
    this.paused = false;
    this.taskId = null;
    this.startedAt = Date.now();
    this.clearTimer();
    this.request?.abort();
    this.patch({
      analysisId: null,
      status: "pending",
      stage: "queued",
      error: null,
      requestPending: true,
    });

    const request = this.newRequest();
    void createAnalysis(imageId, { force, signal: request.signal }).then(
      (created) => {
        if (request.signal.aborted || !this.isCurrent(generation)) {
          return;
        }
        this.taskId = created.analysisId;
        this.patch({
          analysisId: created.analysisId,
          status: created.status,
          stage: created.stage,
          requestPending: false,
        });
        if (isTerminal(created.status)) {
          void this.poll(generation);
        } else {
          this.schedule(generation);
        }
      },
      (error: unknown) => {
        if (request.signal.aborted || !this.isCurrent(generation)) {
          return;
        }
        this.fail(toAnalysisError(error));
      },
    );
  }

  retry(): void {
    this.start(false);
  }

  rerun(): void {
    this.start(true);
  }

  pause(): void {
    if (!this.active) {
      return;
    }
    this.paused = true;
    this.clearTimer();
  }

  resume(): void {
    if (!this.active || !this.paused) {
      return;
    }
    this.paused = false;
    void this.poll(this.generation);
  }

  dispose(): void {
    this.stop();
  }

  private stop(): void {
    this.generation += 1;
    this.active = false;
    this.paused = false;
    this.taskId = null;
    this.clearTimer();
    this.request?.abort();
    this.request = null;
  }

  private isCurrent(generation: number): boolean {
    return this.active && this.generation === generation;
  }

  private patch(patch: Partial<AnalysisState>): void {
    this.state = { ...this.state, ...patch };
    this.emit(this.state);
  }

  private newRequest(): AbortController {
    this.request?.abort();
    const request = new AbortController();
    this.request = request;
    return request;
  }

  private clearTimer(): void {
    if (this.timer !== null) {
      globalThis.clearTimeout(this.timer);
      this.timer = null;
    }
  }

  private schedule(generation: number): void {
    if (!this.isCurrent(generation) || this.paused) {
      return;
    }
    this.clearTimer();
    const elapsed = Date.now() - this.startedAt;
    const delay =
      elapsed < ANALYSIS_FAST_POLL_WINDOW_MS
        ? ANALYSIS_FAST_POLL_MS
        : ANALYSIS_SLOW_POLL_MS;
    this.timer = globalThis.setTimeout(() => {
      this.timer = null;
      void this.poll(generation);
    }, delay);
  }

  private async poll(generation: number): Promise<void> {
    const taskId = this.taskId;
    if (!taskId || !this.isCurrent(generation) || this.paused) {
      return;
    }
    const request = this.newRequest();
    try {
      const response = await fetchAnalysisStatus(taskId, request.signal);
      if (
        request.signal.aborted ||
        !this.isCurrent(generation) ||
        response.analysisId !== taskId
      ) {
        return;
      }
      this.applyStatus(response, generation);
    } catch (error) {
      if (request.signal.aborted || !this.isCurrent(generation)) {
        return;
      }
      this.fail(toAnalysisError(error));
    }
  }

  private applyStatus(
    response: AnalysisStatusResponse,
    generation: number,
  ): void {
    this.patch({
      analysisId: response.analysisId,
      status: response.status,
      stage: response.stage,
      isMock: response.isMock,
      requestPending: false,
    });

    if (response.status === "completed") {
      this.active = false;
      this.clearTimer();
      if (response.result) {
        this.acceptReport(response.result, generation);
      } else if (response.resultAvailable) {
        void this.loadReport(response.analysisId, generation);
      } else {
        this.fail(UNAVAILABLE_ERROR);
      }
      return;
    }

    if (response.status === "failed") {
      this.active = false;
      this.clearTimer();
      this.patch({
        error: response.error
          ? {
              code: response.error.code,
              message: analysisFailureMessage(response.error.code, response.error.message),
              requestId: null,
            }
          : DEFAULT_FAILURE,
        requestPending: false,
      });
      return;
    }

    this.schedule(generation);
  }

  private async loadReport(
    taskId: string,
    generation: number,
  ): Promise<void> {
    const request = this.newRequest();
    try {
      const report = await fetchAnalysisReport(taskId, request.signal);
      if (request.signal.aborted || this.generation !== generation) {
        return;
      }
      this.acceptReport(report, generation);
    } catch (error) {
      if (request.signal.aborted || this.generation !== generation) {
        return;
      }
      this.fail(toAnalysisError(error));
    }
  }

  private acceptReport(report: AnalysisReport, generation: number): void {
    if (this.generation !== generation) {
      return;
    }
    if (report.image.id !== this.imageId) {
      this.fail(MISMATCH_ERROR);
      return;
    }
    this.patch({ report, error: null, requestPending: false });
  }

  private fail(error: AnalysisError): void {
    this.active = false;
    this.clearTimer();
    const interrupted =
      this.state.status === "pending" || this.state.status === "processing";
    this.patch({
      error,
      requestPending: false,
      status: interrupted ? "failed" : this.state.status,
      stage: interrupted ? "failed" : this.state.stage,
    });
  }
}

export function useAnalysis(imageId: string | null): UseAnalysisResult {
  const [state, setState] = useState<AnalysisState>(INITIAL_STATE);
  const [controller] = useState(() => new AnalysisController(setState));

  useEffect(() => {
    controller.setImage(imageId);
  }, [controller, imageId]);

  useEffect(() => () => controller.dispose(), [controller]);

  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === "hidden") {
        controller.pause();
      } else {
        controller.resume();
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [controller]);

  const start = useCallback(
    (force?: boolean) => controller.start(force ?? false),
    [controller],
  );
  const retry = useCallback(() => controller.retry(), [controller]);
  const rerun = useCallback(() => controller.rerun(), [controller]);
  const running =
    state.requestPending ||
    state.status === "pending" ||
    state.status === "processing";

  return { ...state, running, start, retry, rerun };
}