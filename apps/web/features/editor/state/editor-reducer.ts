import type { EditorError } from "@/lib/error-messages";
import {
  DEFAULT_RECIPE_FINGERPRINT,
  normalizeRecipe,
  recipeFingerprint,
  withAdjustment,
  withCrop,
  type NumericAdjustmentKey,
} from "@/lib/recipe";
import type {
  Crop,
  EditorRecipe,
  EditRecipe,
  RevisionSummary,
  SessionState,
} from "@/types/session";

export type EditorPhase = "empty" | "uploading" | "creatingSession" | "ready" | "exporting";
export type PreviewQuality = "draft" | "final";
export type PreviewStatus = "idle" | "loading" | "ready" | "error";
export type SaveStatus = "saved" | "saving" | "unsaved" | "error";

export interface PreviewState {
  url: string | null;
  width: number;
  height: number;
  quality: PreviewQuality | null;
  status: PreviewStatus;
  seq: number;
  version: number;
  error: EditorError | null;
}

export interface EditorSaveState {
  status: SaveStatus;
  idempotencyKey: string | null;
  idempotencyFingerprint: string | null;
  error: EditorError | null;
  retryable: boolean;
}

export interface EditorState {
  phase: EditorPhase;
  sessionId: string | null;
  imageId: string | null;
  committed: EditorRecipe;
  draft: EditorRecipe;
  activeRevisionId: string | null;
  headRevisionId: string | null;
  canUndo: boolean;
  canRedo: boolean;
  history: RevisionSummary[];
  historyCursor: number | null;
  preview: PreviewState;
  save: EditorSaveState;
  notice: string | null;
  error: EditorError | null;
}

export type EditorAction =
  | { type: "upload-start" }
  | { type: "upload-failed"; error: EditorError }
  | { type: "session-loading" }
  | { type: "session-ready"; state: SessionState }
  | { type: "session-load-failed"; error: EditorError }
  | { type: "history-loaded"; items: RevisionSummary[]; nextCursor: number | null }
  | { type: "draft-adjustment"; key: NumericAdjustmentKey; value: number }
  | { type: "draft-crop"; crop: Crop | null }
  | { type: "draft-recipe"; recipe: EditRecipe }
  | { type: "draft-discard" }
  | { type: "preview-loading"; seq: number }
  | {
      type: "preview-ready";
      seq: number;
      url: string;
      width: number;
      height: number;
      quality: PreviewQuality;
    }
  | { type: "preview-error"; seq: number; error: EditorError }
  | { type: "save-start"; idempotencyKey: string; fingerprint: string }
  | { type: "save-success"; state: SessionState }
  | { type: "save-failure"; error: EditorError; retryable: boolean }
  | { type: "session-replaced"; state: SessionState }
  | { type: "conflict"; state: SessionState }
  | { type: "export-start" }
  | { type: "export-finished" }
  | { type: "notice-cleared" }
  | { type: "error"; error: EditorError }
  | { type: "error-cleared" }
  | { type: "reset-editor" };

export const CONFLICT_NOTICE = "版本已变化，已为你刷新。";

function initialPreview(): PreviewState {
  return {
    url: null,
    width: 0,
    height: 0,
    quality: null,
    status: "idle",
    seq: 0,
    version: 0,
    error: null,
  };
}

function initialSave(): EditorSaveState {
  return {
    status: "saved",
    idempotencyKey: null,
    idempotencyFingerprint: null,
    error: null,
    retryable: false,
  };
}

export function createInitialEditorState(): EditorState {
  const recipe = normalizeRecipe({
    schemaVersion: "1.0",
    styleId: "natural",
    styleStrength: 0,
  });
  return {
    phase: "empty",
    sessionId: null,
    imageId: null,
    committed: recipe,
    draft: recipe,
    activeRevisionId: null,
    headRevisionId: null,
    canUndo: false,
    canRedo: false,
    history: [],
    historyCursor: null,
    preview: initialPreview(),
    save: initialSave(),
    notice: null,
    error: null,
  };
}

function fromSession(session: SessionState) {
  const recipe = normalizeRecipe(session.revision.recipe);
  return {
    sessionId: session.sessionId,
    imageId: session.imageId,
    committed: recipe,
    draft: recipe,
    activeRevisionId: session.activeRevisionId,
    headRevisionId: session.headRevisionId,
    canUndo: session.canUndo,
    canRedo: session.canRedo,
  };
}

function syncDraft(state: EditorState, draft: EditorRecipe): EditorState {
  const dirty = recipeFingerprint(draft) !== recipeFingerprint(state.committed);
  if (!dirty) {
    return { ...state, draft, save: initialSave() };
  }
  if (state.save.status === "saving") {
    return { ...state, draft };
  }
  return {
    ...state,
    draft,
    save: {
      ...state.save,
      status: state.save.status === "error" ? "error" : "unsaved",
    },
  };
}

function isStale(state: EditorState, seq: number): boolean {
  return seq < state.preview.seq;
}

export function editorReducer(state: EditorState, action: EditorAction): EditorState {
  switch (action.type) {
    case "upload-start":
      return { ...state, phase: "uploading", error: null };

    case "upload-failed":
      return { ...state, phase: "empty", error: action.error };

    case "session-loading":
      return { ...createInitialEditorState(), phase: "creatingSession" };

    case "session-ready": {
      const snapshot = fromSession(action.state);
      return {
        ...state,
        ...snapshot,
        phase: "ready",
        history: [],
        historyCursor: null,
        preview: { ...initialPreview(), status: "loading" },
        save: initialSave(),
        notice: null,
        error: null,
      };
    }

    case "session-load-failed":
      return {
        ...createInitialEditorState(),
        error: action.error,
      };

    case "history-loaded":
      return {
        ...state,
        history: action.items,
        historyCursor: action.nextCursor,
      };

    case "draft-adjustment":
      return syncDraft(state, withAdjustment(state.draft, action.key, action.value));

    case "draft-crop":
      return syncDraft(state, withCrop(state.draft, action.crop));

    case "draft-recipe":
      return syncDraft(state, normalizeRecipe(action.recipe));

    case "draft-discard":
      return {
        ...state,
        draft: state.committed,
        save: initialSave(),
        notice: null,
      };

    case "preview-loading":
      if (isStale(state, action.seq)) {
        return state;
      }
      return {
        ...state,
        preview: {
          ...state.preview,
          seq: action.seq,
          status: "loading",
          error: null,
        },
      };

    case "preview-ready":
      if (isStale(state, action.seq)) {
        return state;
      }
      return {
        ...state,
        preview: {
          url: action.url,
          width: action.width,
          height: action.height,
          quality: action.quality,
          status: "ready",
          seq: action.seq,
          version: state.preview.version + 1,
          error: null,
        },
      };

    case "preview-error":
      if (isStale(state, action.seq)) {
        return state;
      }
      return {
        ...state,
        preview: {
          ...state.preview,
          seq: action.seq,
          status: "error",
          error: action.error,
        },
      };

    case "save-start":
      return {
        ...state,
        save: {
          status: "saving",
          idempotencyKey: action.idempotencyKey,
          idempotencyFingerprint: action.fingerprint,
          error: null,
          retryable: false,
        },
        error: null,
      };

    case "save-success": {
      const committed = normalizeRecipe(action.state.revision.recipe);
      const upToDate = recipeFingerprint(state.draft) === recipeFingerprint(committed);
      return {
        ...state,
        committed,
        draft: upToDate ? committed : state.draft,
        activeRevisionId: action.state.activeRevisionId,
        headRevisionId: action.state.headRevisionId,
        canUndo: action.state.canUndo,
        canRedo: action.state.canRedo,
        save: upToDate
          ? initialSave()
          : {
              status: "unsaved",
              idempotencyKey: null,
              idempotencyFingerprint: null,
              error: null,
              retryable: false,
            },
        notice: null,
        error: null,
      };
    }

    case "save-failure":
      return {
        ...state,
        save: {
          status: "error",
          idempotencyKey: action.retryable ? state.save.idempotencyKey : null,
          idempotencyFingerprint: action.retryable
            ? state.save.idempotencyFingerprint
            : null,
          error: action.error,
          retryable: action.retryable,
        },
      };

    case "session-replaced": {
      const snapshot = fromSession(action.state);
      return {
        ...state,
        ...snapshot,
        save: initialSave(),
        preview: { ...state.preview, status: "loading", error: null },
        notice: null,
        error: null,
      };
    }

    case "conflict": {
      const snapshot = fromSession(action.state);
      return {
        ...state,
        ...snapshot,
        draft: state.draft,
        save: {
          status: "unsaved",
          idempotencyKey: null,
          idempotencyFingerprint: null,
          error: null,
          retryable: false,
        },
        preview: { ...state.preview, status: "loading", error: null },
        notice: CONFLICT_NOTICE,
        error: null,
      };
    }

    case "export-start":
      return { ...state, phase: "exporting" };

    case "export-finished":
      return { ...state, phase: state.phase === "exporting" ? "ready" : state.phase };

    case "notice-cleared":
      return { ...state, notice: null };

    case "error":
      return { ...state, error: action.error };

    case "error-cleared":
      return { ...state, error: null };

    case "reset-editor":
      return createInitialEditorState();

    default: {
      const exhaustive: never = action;
      return exhaustive;
    }
  }
}

export function selectIsDirty(state: EditorState): boolean {
  return recipeFingerprint(state.draft) !== recipeFingerprint(state.committed);
}

export function selectCanSave(state: EditorState): boolean {
  return (
    state.phase === "ready" &&
    state.save.status !== "saving" &&
    selectIsDirty(state)
  );
}

export function selectCanUndo(state: EditorState): boolean {
  return state.phase === "ready" && state.canUndo && state.save.status !== "saving";
}

export function selectCanRedo(state: EditorState): boolean {
  return state.phase === "ready" && state.canRedo && state.save.status !== "saving";
}

export function selectCanReset(state: EditorState): boolean {
  return (
    state.phase === "ready" &&
    state.save.status !== "saving" &&
    recipeFingerprint(state.committed) !== DEFAULT_RECIPE_FINGERPRINT
  );
}

export function selectCanExport(state: EditorState): boolean {
  return state.phase === "ready" && state.activeRevisionId !== null;
}
