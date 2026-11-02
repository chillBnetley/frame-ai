"use client";

import { useCallback, useRef, useState } from "react";

import { useEditorDispatch, useEditorState } from "@/features/editor/state/editor-context";
import { exportSession } from "@/lib/api/sessions";
import { describeEditorError, type EditorError } from "@/lib/error-messages";
import type { ExportFormat } from "@/types/session";

export type ExportStatus = "idle" | "exporting" | "success" | "error";

export interface ExportState {
  status: ExportStatus;
  error: EditorError | null;
  filename: string | null;
  width: number | null;
  height: number | null;
}

export interface UseExportResult {
  state: ExportState;
  exportImage: (options: {
    revisionId: string;
    format: ExportFormat;
    quality?: number | null;
  }) => Promise<boolean>;
  reset: () => void;
}

const INITIAL_STATE: ExportState = {
  status: "idle",
  error: null,
  filename: null,
  width: null,
  height: null,
};

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

  const exportImage = useCallback(
    async (options: {
      revisionId: string;
      format: ExportFormat;
      quality?: number | null;
    }): Promise<boolean> => {
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
      });

      try {
        const result = await exportSession(sessionId, options);
        triggerDownload(result.blob, result.filename);
        setExportState({
          status: "success",
          error: null,
          filename: result.filename,
          width: result.width,
          height: result.height,
        });
        return true;
      } catch (error) {
        setExportState({
          status: "error",
          error: describeEditorError(error),
          filename: null,
          width: null,
          height: null,
        });
        return false;
      } finally {
        exportingRef.current = false;
        dispatch({ type: "export-finished" });
      }
    },
    [dispatch, sessionId],
  );

  const reset = useCallback(() => setExportState(INITIAL_STATE), []);

  return { state: exportState, exportImage, reset };
}
