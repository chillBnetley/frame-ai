"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useEditorDispatch, useEditorState } from "@/features/editor/state/editor-context";
import { ApiClientError } from "@/lib/api/client";
import {
  cancelExportJob,
  createExportJob,
  downloadExportResult,
  exportJobError,
  getExportJob,
  type ExportJob,
} from "@/lib/api/sessions";
import { describeEditorError, type EditorError } from "@/lib/error-messages";
import type { ExportBitDepth, ExportFormat } from "@/types/session";

export type ExportStatus = "idle" | "exporting" | "success" | "error" | "cancelled";

export interface ExportState {
  status: ExportStatus;
  error: EditorError | null;
  filename: string | null;
  width: number | null;
  height: number | null;
  bytes: number | null;
  warnings: string[];
}

export interface ExportImageOptions {
  revisionId: string;
  format: ExportFormat;
  quality?: number | null;
  maxEdge?: number | null;
  bitDepth?: ExportBitDepth;
}

export interface UseExportResult {
  state: ExportState;
  exportImage: (options: ExportImageOptions) => Promise<boolean>;
  cancel: () => Promise<void>;
  reset: () => void;
}

const INITIAL_STATE: ExportState = {
  status: "idle",
  error: null,
  filename: null,
  width: null,
  height: null,
  bytes: null,
  warnings: [],
};

const JOB_POLL_INITIAL_MS = 400;
const JOB_POLL_MAX_MS = 1_500;
const JOB_TIMEOUT_MS = 10 * 60_000;

function abortError(): DOMException {
  return new DOMException("Export polling aborted", "AbortError");
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(abortError());
      return;
    }
    const timer = globalThis.setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      globalThis.clearTimeout(timer);
      reject(abortError());
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

async function waitForJob(jobId: string, signal: AbortSignal): Promise<ExportJob> {
  const deadline = Date.now() + JOB_TIMEOUT_MS;
  let delay = JOB_POLL_INITIAL_MS;
  for (;;) {
    const job = await getExportJob(jobId, signal);
    if (job.status !== "queued" && job.status !== "running") {
      return job;
    }
    if (Date.now() >= deadline) {
      await cancelExportJob(jobId).catch(() => undefined);
      throw new ApiClientError(
        "export_timeout",
        "导出作业超时，已请求取消，请稍后重试。",
      );
    }
    await sleep(delay, signal);
    delay = Math.min(Math.round(delay * 1.4), JOB_POLL_MAX_MS);
  }
}

function triggerDownload(blob: Blob, filename: string): void {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.rel = "noopener";
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  try {
    anchor.click();
  } finally {
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
  }
}

export function useExport(): UseExportResult {
  const { sessionId } = useEditorState();
  const dispatch = useEditorDispatch();
  const [exportState, setExportState] = useState<ExportState>(INITIAL_STATE);
  const exportingRef = useRef(false);
  const jobRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const markCancelled = useCallback(() => {
    setExportState((previous) =>
      previous.status === "exporting"
        ? { ...previous, status: "cancelled", error: null }
        : previous,
    );
  }, []);

  const cancel = useCallback(async () => {
    const jobId = jobRef.current;
    abortRef.current?.abort();
    if (jobId !== null) {
      // The job may have finished between the click and this request; a
      // completed job is still a valid 204 no-op, not an error.
      await cancelExportJob(jobId).catch(() => undefined);
    }
    markCancelled();
  }, [markCancelled]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      const jobId = jobRef.current;
      if (jobId !== null) {
        void cancelExportJob(jobId).catch(() => undefined);
      }
    };
  }, []);

  const exportImage = useCallback(
    async (options: ExportImageOptions): Promise<boolean> => {
      if (sessionId === null || exportingRef.current) {
        return false;
      }

      exportingRef.current = true;
      dispatch({ type: "export-start" });
      setExportState({
        status: "exporting",
        error: null,
        filename: null,
        width: null,
        height: null,
        bytes: null,
        warnings: [],
      });
      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const created = await createExportJob(sessionId, options, controller.signal);
        jobRef.current = created.jobId;
        const finished = await waitForJob(created.jobId, controller.signal);
        if (finished.status === "cancelled") {
          markCancelled();
          return false;
        }
        if (finished.status !== "succeeded") {
          throw exportJobError(finished);
        }
        const result = await downloadExportResult(
          created.jobId,
          options.format,
          controller.signal,
        );
        triggerDownload(result.blob, result.filename);
        setExportState({
          status: "success",
          error: null,
          filename: result.filename,
          width: result.width,
          height: result.height,
          bytes: result.blob.size,
          warnings: result.warnings,
        });
        return true;
      } catch (error) {
        if (controller.signal.aborted) {
          markCancelled();
          return false;
        }
        setExportState({
          status: "error",
          error: describeEditorError(error),
          filename: null,
          width: null,
          height: null,
          bytes: null,
          warnings: [],
        });
        return false;
      } finally {
        jobRef.current = null;
        if (abortRef.current === controller) {
          abortRef.current = null;
        }
        exportingRef.current = false;
        dispatch({ type: "export-finished" });
      }
    },
    [dispatch, markCancelled, sessionId],
  );

  const reset = useCallback(() => setExportState(INITIAL_STATE), []);

  return { state: exportState, exportImage, cancel, reset };
}
