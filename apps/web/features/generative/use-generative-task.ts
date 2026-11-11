"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiClientError } from "@/lib/api/client";
import {
  acceptGenerativeResult,
  cancelGenerativeTask,
  createGenerativeTask,
  pollGenerativeTask,
  rejectGenerativeResult,
  retryGenerativeTask,
} from "@/lib/api/generative";
import type {
  GenerativeResultView,
  GenerativeTaskRequest,
  GenerativeTaskStatusResponse,
} from "@/types/generative";
import type { SessionState } from "@/types/session";

const DEFAULT_POLL_INTERVAL_MS = 300;

const RUNNING_STATUSES = new Set(["created", "validating", "queued", "processing"]);

export interface GenerativeTaskCopy {
  submitFailed: string;
  retryFailed: string;
  acceptFailed: string;
  rejectFailed: string;
  taskFailed: string;
}

const DEFAULT_COPY: GenerativeTaskCopy = {
  submitFailed: "提交生成任务失败，请检查网络或参数。",
  retryFailed: "重试任务失败，请稍后再试。",
  acceptFailed: "采纳结果失败，版本未发生变化。",
  rejectFailed: "放弃结果失败，请稍后再试。",
  taskFailed: "生成任务未成功完成。",
};

export interface UseGenerativeTaskOptions {
  intervalMs?: number;
  copy?: Partial<GenerativeTaskCopy>;
  onAccepted?: (state: SessionState) => void;
  onRejected?: () => void;
}

export interface GenerativeErrorPayload {
  code: string | null;
  message: string;
  requestId: string | null;
}

export interface GenerativeTaskController {
  task: GenerativeTaskStatusResponse | null;
  status: GenerativeTaskStatusResponse["status"] | null;
  stage: GenerativeTaskStatusResponse["stage"] | null;
  candidates: GenerativeResultView[];
  isRunning: boolean;
  isSubmitting: boolean;
  isAccepting: boolean;
  error: string | null;
  errorInfo: GenerativeErrorPayload | null;
  submit: (request: GenerativeTaskRequest) => Promise<boolean>;
  cancel: () => Promise<void>;
  retry: () => Promise<void>;
  accept: (resultId: string) => Promise<boolean>;
  reject: (resultId: string) => Promise<boolean>;
  notify: (message: string | null) => void;
  reset: () => void;
}

function errorPayload(error: unknown, fallback: string): GenerativeErrorPayload {
  if (error instanceof ApiClientError) {
    return { code: error.code, message: error.message || fallback, requestId: error.requestId };
  }
  if (error instanceof Error && error.message) {
    return { code: null, message: error.message, requestId: null };
  }
  return { code: null, message: fallback, requestId: null };
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export function useGenerativeTask(
  options: UseGenerativeTaskOptions = {},
): GenerativeTaskController {
  const intervalMs = options.intervalMs ?? DEFAULT_POLL_INTERVAL_MS;
  const submitFailed = options.copy?.submitFailed ?? DEFAULT_COPY.submitFailed;
  const retryFailed = options.copy?.retryFailed ?? DEFAULT_COPY.retryFailed;
  const acceptFailed = options.copy?.acceptFailed ?? DEFAULT_COPY.acceptFailed;
  const rejectFailed = options.copy?.rejectFailed ?? DEFAULT_COPY.rejectFailed;
  const taskFailed = options.copy?.taskFailed ?? DEFAULT_COPY.taskFailed;
  const onAccepted = options.onAccepted;
  const onRejected = options.onRejected;

  const [task, setTask] = useState<GenerativeTaskStatusResponse | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isAccepting, setIsAccepting] = useState(false);
  const [errorInfo, setErrorInfo] = useState<GenerativeErrorPayload | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const activeTaskIdRef = useRef<string | null>(null);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const pollUntilSettled = useCallback(
    async (taskId: string, signal: AbortSignal): Promise<GenerativeTaskStatusResponse> => {
      const settled = await pollGenerativeTask(
        taskId,
        { intervalMs, onUpdate: (next) => setTask(next) },
        signal,
      );
      setTask(settled);
      if (settled.status === "failed") {
        setErrorInfo({
          code: settled.error?.code ?? null,
          message: settled.error?.message || taskFailed,
          requestId: null,
        });
      }
      return settled;
    },
    [intervalMs, taskFailed],
  );

  const submit = useCallback(
    async (request: GenerativeTaskRequest): Promise<boolean> => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setErrorInfo(null);
      setIsSubmitting(true);
      try {
        const created = await createGenerativeTask(request, undefined, controller.signal);
        activeTaskIdRef.current = created.taskId;
        await pollUntilSettled(created.taskId, controller.signal);
        return true;
      } catch (caught) {
        if (!isAbortError(caught)) {
          setErrorInfo(errorPayload(caught, submitFailed));
        }
        return false;
      } finally {
        setIsSubmitting(false);
      }
    },
    [pollUntilSettled, submitFailed],
  );

  const cancel = useCallback(async (): Promise<void> => {
    const taskId = task?.taskId ?? activeTaskIdRef.current;
    if (!taskId) {
      return;
    }
    abortRef.current?.abort();
    setErrorInfo(null);
    try {
      const cancelled = await cancelGenerativeTask(taskId);
      setTask(cancelled);
    } catch {
      // A task that already settled cannot be cancelled; the last known state stands.
    }
  }, [task]);

  const retry = useCallback(async (): Promise<void> => {
    const taskId = task?.taskId ?? activeTaskIdRef.current;
    if (!taskId) {
      return;
    }
    const controller = new AbortController();
    abortRef.current = controller;
    setErrorInfo(null);
    setIsSubmitting(true);
    try {
      const restarted = await retryGenerativeTask(taskId);
      if (controller.signal.aborted) {
        return;
      }
      setTask(restarted);
      await pollUntilSettled(restarted.taskId, controller.signal);
    } catch (caught) {
      if (!isAbortError(caught)) {
        setErrorInfo(errorPayload(caught, retryFailed));
      }
    } finally {
      setIsSubmitting(false);
    }
  }, [pollUntilSettled, retryFailed, task]);

  const accept = useCallback(
    async (resultId: string): Promise<boolean> => {
      setErrorInfo(null);
      setIsAccepting(true);
      try {
        const state = await acceptGenerativeResult(resultId);
        activeTaskIdRef.current = null;
        setTask(null);
        onAccepted?.(state);
        return true;
      } catch (caught) {
        setErrorInfo(errorPayload(caught, acceptFailed));
        return false;
      } finally {
        setIsAccepting(false);
      }
    },
    [acceptFailed, onAccepted],
  );

  const reject = useCallback(
    async (resultId: string): Promise<boolean> => {
      setErrorInfo(null);
      try {
        await rejectGenerativeResult(resultId);
        activeTaskIdRef.current = null;
        setTask(null);
        onRejected?.();
        return true;
      } catch (caught) {
        setErrorInfo(errorPayload(caught, rejectFailed));
        return false;
      }
    },
    [onRejected, rejectFailed],
  );

  const isRunning = task !== null && RUNNING_STATUSES.has(task.status);
  const candidates: GenerativeResultView[] =
    task?.status === "succeeded" && task.results ? task.results : [];

  const notify = useCallback((message: string | null): void => {
    setErrorInfo(message === null ? null : { code: null, message, requestId: null });
  }, []);

  return {
    task,
    status: task?.status ?? null,
    stage: task?.stage ?? null,
    candidates,
    isRunning,
    isSubmitting,
    isAccepting,
    error: errorInfo?.message ?? null,
    errorInfo,
    submit,
    cancel,
    retry,
    accept,
    reject,
    notify,
    reset: () => {
      abortRef.current?.abort();
      activeTaskIdRef.current = null;
      setTask(null);
      setErrorInfo(null);
    },
  };
}
