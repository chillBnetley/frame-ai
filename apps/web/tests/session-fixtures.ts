import {
  createInitialEditorState,
  editorReducer,
  type EditorState,
} from "@/features/editor/state/editor-reducer";
import { normalizeRecipe } from "@/lib/recipe";
import type {
  EditRecipe,
  RevisionSource,
  SessionState,
} from "@/types/session";

export const SESSION_ID = "11111111-1111-4111-8111-111111111111";
export const IMAGE_ID = "22222222-2222-4222-8222-222222222222";
export const REVISION_ID = "33333333-3333-4333-8333-333333333333";
export const NEXT_REVISION_ID = "44444444-4444-4444-8444-444444444444";
export const THIRD_REVISION_ID = "55555555-5555-4555-8555-555555555555";

interface SessionStateOptions {
  recipe?: EditRecipe;
  revisionId?: string;
  headRevisionId?: string;
  revisionNo?: number;
  source?: RevisionSource;
  canUndo?: boolean;
  canRedo?: boolean;
  sessionId?: string;
  baseWidth?: number;
  baseHeight?: number;
}

export function sessionState(options: SessionStateOptions = {}): SessionState {
  const revisionId = options.revisionId ?? REVISION_ID;
  const revisionNo = options.revisionNo ?? 1;
  return {
    sessionId: options.sessionId ?? SESSION_ID,
    imageId: IMAGE_ID,
    activeRevisionId: revisionId,
    headRevisionId: options.headRevisionId ?? revisionId,
    canUndo: options.canUndo ?? false,
    canRedo: options.canRedo ?? false,
    revision: {
      id: revisionId,
      revisionNo,
      parentId: revisionNo > 1 ? NEXT_REVISION_ID : null,
      source: options.source ?? (revisionNo > 1 ? "user" : "initial"),
      recipe: normalizeRecipe(options.recipe),
      baseWidth: options.baseWidth ?? 800,
      baseHeight: options.baseHeight ?? 600,
      createdAt: "2026-11-02T00:00:00Z",
    },
  };
}

export function readyEditorState(
  recipe?: EditRecipe,
  options: SessionStateOptions = {},
): EditorState {
  return editorReducer(createInitialEditorState(), {
    type: "session-ready",
    state: sessionState({ ...options, recipe }),
  });
}
