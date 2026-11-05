import { describe, expect, it } from "vitest";

import {
  CONFLICT_NOTICE,
  createInitialEditorState,
  editorReducer,
  selectCanExport,
  selectCanRedo,
  selectCanReset,
  selectCanSave,
  selectCanUndo,
  selectIsDirty,
} from "@/features/editor/state/editor-reducer";
import { withAdjustment } from "@/lib/recipe";
import type { EditorError } from "@/lib/error-messages";
import {
  NEXT_REVISION_ID,
  REVISION_ID,
  readyEditorState,
  sessionState,
} from "./session-fixtures";

const NETWORK_ERROR: EditorError = {
  code: "network_error",
  message: "无法连接后端服务。请确认已启动 API。",
  details: {},
};

function previewReady(seq: number, url: string, warnings: string[] = []) {
  return {
    type: "preview-ready" as const,
    seq,
    url,
    width: 1600,
    height: 1200,
    quality: "final" as const,
    warnings,
  };
}

describe("editorReducer session lifecycle", () => {
  it("starts empty and only becomes ready with a server session", () => {
    const initial = createInitialEditorState();
    expect(initial.phase).toBe("empty");
    expect(initial.sessionId).toBeNull();
    expect(selectCanSave(initial)).toBe(false);

    const loading = editorReducer(initial, { type: "session-loading" });
    expect(loading.phase).toBe("creatingSession");

    const ready = editorReducer(loading, {
      type: "session-ready",
      state: sessionState({ canUndo: true }),
    });
    expect(ready.phase).toBe("ready");
    expect(ready.sessionId).toBe("11111111-1111-4111-8111-111111111111");
    expect(ready.activeRevisionId).toBe(REVISION_ID);
    expect(ready.committed).toEqual(ready.draft);
    expect(ready.canUndo).toBe(true);
  });

  it("stores load failures without leaving a half-open session", () => {
    const failed = editorReducer(createInitialEditorState(), {
      type: "session-load-failed",
      error: NETWORK_ERROR,
    });

    expect(failed.phase).toBe("empty");
    expect(failed.sessionId).toBeNull();
    expect(failed.error).toEqual(NETWORK_ERROR);
  });

  it("keeps history items from the revisions list", () => {
    const ready = readyEditorState();
    const withHistory = editorReducer(ready, {
      type: "history-loaded",
      items: [
        {
          id: REVISION_ID,
          revisionNo: 1,
          parentId: null,
          source: "initial",
          recipeHash: "a".repeat(64),
          createdAt: "2026-11-02T00:00:00Z",
        },
      ],
      nextCursor: null,
    });

    expect(withHistory.history).toHaveLength(1);
    expect(withHistory.history[0]?.id).toBe(REVISION_ID);
  });
});

describe("editorReducer draft handling", () => {
  it("rounds and clamps draft edits, marking them unsaved", () => {
    const ready = readyEditorState();
    const edited = editorReducer(ready, {
      type: "draft-adjustment",
      key: "contrast",
      value: 140.126,
    });

    expect(edited.draft.adjustments.contrast).toBe(100);
    expect(edited.committed.adjustments.contrast).toBe(0);
    expect(edited.save.status).toBe("unsaved");
    expect(selectIsDirty(edited)).toBe(true);
    expect(selectCanSave(edited)).toBe(true);
  });

  it("becomes saved again when the draft returns to the committed value", () => {
    const ready = readyEditorState();
    const edited = editorReducer(ready, {
      type: "draft-adjustment",
      key: "contrast",
      value: 20,
    });
    const reverted = editorReducer(edited, {
      type: "draft-adjustment",
      key: "contrast",
      value: 0,
    });

    expect(selectIsDirty(reverted)).toBe(false);
    expect(reverted.save.status).toBe("saved");
    expect(selectCanSave(reverted)).toBe(false);
  });

  it("discards the draft without moving the committed recipe", () => {
    const ready = readyEditorState();
    const edited = editorReducer(ready, { type: "draft-crop", crop: { x: 0.1, y: 0.1, w: 0.5, h: 0.5 } });
    const discarded = editorReducer(edited, { type: "draft-discard" });

    expect(discarded.draft).toEqual(ready.committed);
    expect(discarded.committed).toEqual(ready.committed);
    expect(discarded.save.status).toBe("saved");
  });
});

describe("editorReducer preview ordering", () => {
  it("keeps the previous preview while a new render is loading", () => {
    const ready = readyEditorState();
    const first = editorReducer(ready, previewReady(1, "/api/v1/previews/first"));
    const loading = editorReducer(first, { type: "preview-loading", seq: 2 });

    expect(loading.preview.url).toBe("/api/v1/previews/first");
    expect(loading.preview.status).toBe("loading");
  });

  it("ignores stale preview responses", () => {
    let state = editorReducer(readyEditorState(), previewReady(1, "/first"));
    state = editorReducer(state, { type: "preview-loading", seq: 2 });
    state = editorReducer(state, previewReady(2, "/second"));
    const stale = editorReducer(state, previewReady(1, "/stale"));

    expect(stale.preview.url).toBe("/second");
    expect(stale.preview.status).toBe("ready");
    expect(stale.preview.seq).toBe(2);
  });

  it("ignores a stale preview error", () => {
    let state = editorReducer(readyEditorState(), previewReady(2, "/second"));
    const stale = editorReducer(state, {
      type: "preview-error",
      seq: 1,
      error: NETWORK_ERROR,
    });

    expect(stale.preview.status).toBe("ready");
    expect(stale.preview.error).toBeNull();

    state = editorReducer(stale, { type: "preview-error", seq: 3, error: NETWORK_ERROR });
    expect(state.preview.status).toBe("error");
    expect(state.preview.url).toBe("/second");
  });

  it("replaces render warnings with each successful preview", () => {
    const warned = editorReducer(
      readyEditorState(),
      previewReady(1, "/first", ["local_mask_missing:mask_gone"]),
    );
    expect(warned.preview.warnings).toEqual(["local_mask_missing:mask_gone"]);

    const clean = editorReducer(warned, previewReady(2, "/second"));
    expect(clean.preview.warnings).toEqual([]);
  });
});

describe("editorReducer commit lifecycle", () => {
  it("keeps the draft and the idempotency key after a retryable failure", () => {
    let state = editorReducer(readyEditorState(), {
      type: "draft-adjustment",
      key: "contrast",
      value: 20,
    });
    state = editorReducer(state, {
      type: "save-start",
      idempotencyKey: "key-1",
      fingerprint: "fingerprint-1",
    });
    state = editorReducer(state, {
      type: "save-failure",
      error: NETWORK_ERROR,
      retryable: true,
    });

    expect(state.draft.adjustments.contrast).toBe(20);
    expect(state.save.status).toBe("error");
    expect(state.save.error).toEqual(NETWORK_ERROR);
    expect(state.save.idempotencyKey).toBe("key-1");
    expect(state.save.retryable).toBe(true);
  });

  it("drops the idempotency key for non-retryable failures", () => {
    let state = editorReducer(readyEditorState(), {
      type: "draft-adjustment",
      key: "contrast",
      value: 20,
    });
    state = editorReducer(state, {
      type: "save-start",
      idempotencyKey: "key-1",
      fingerprint: "fingerprint-1",
    });
    state = editorReducer(state, {
      type: "save-failure",
      error: { ...NETWORK_ERROR, code: "validation_error" },
      retryable: false,
    });

    expect(state.save.idempotencyKey).toBeNull();
    expect(state.save.retryable).toBe(false);
    expect(state.draft.adjustments.contrast).toBe(20);
  });

  it("adopts the server revision and clears the key on success", () => {
    const editedRecipe = withAdjustment(readyEditorState().draft, "contrast", 20);
    let state = editorReducer(readyEditorState(), { type: "draft-recipe", recipe: editedRecipe });
    state = editorReducer(state, {
      type: "save-start",
      idempotencyKey: "key-1",
      fingerprint: "fingerprint-1",
    });
    state = editorReducer(state, {
      type: "save-success",
      state: sessionState({
        recipe: editedRecipe,
        revisionId: NEXT_REVISION_ID,
        revisionNo: 2,
        canUndo: true,
      }),
    });

    expect(state.committed.adjustments.contrast).toBe(20);
    expect(state.draft.adjustments.contrast).toBe(20);
    expect(state.activeRevisionId).toBe(NEXT_REVISION_ID);
    expect(state.save.status).toBe("saved");
    expect(state.save.idempotencyKey).toBeNull();
    expect(state.canUndo).toBe(true);
  });

  it("does not clobber a draft that changed while the save was in flight", () => {
    let state = editorReducer(readyEditorState(), {
      type: "draft-adjustment",
      key: "contrast",
      value: 20,
    });
    state = editorReducer(state, {
      type: "save-start",
      idempotencyKey: "key-1",
      fingerprint: "fingerprint-1",
    });
    state = editorReducer(state, { type: "draft-adjustment", key: "contrast", value: 35 });
    state = editorReducer(state, {
      type: "save-success",
      state: sessionState({
        recipe: withAdjustment(state.committed, "contrast", 20),
        revisionId: NEXT_REVISION_ID,
        revisionNo: 2,
        canUndo: true,
      }),
    });

    expect(state.committed.adjustments.contrast).toBe(20);
    expect(state.draft.adjustments.contrast).toBe(35);
    expect(state.save.status).toBe("unsaved");
    expect(state.save.idempotencyKey).toBeNull();
  });
});

describe("editorReducer history and conflicts", () => {
  it("replaces both recipes after a history action", () => {
    const ready = readyEditorState(undefined, {
      recipe: withAdjustment(readyEditorState().draft, "contrast", 18),
      revisionId: NEXT_REVISION_ID,
      revisionNo: 2,
      canUndo: true,
    });
    const replaced = editorReducer(ready, {
      type: "session-replaced",
      state: sessionState({ canRedo: true }),
    });

    expect(replaced.committed.adjustments.contrast).toBe(0);
    expect(replaced.draft.adjustments.contrast).toBe(0);
    expect(replaced.canRedo).toBe(true);
    expect(replaced.save.status).toBe("saved");
  });

  it("refreshes the server state on conflict without overwriting the draft", () => {
    let state = editorReducer(readyEditorState(), {
      type: "draft-adjustment",
      key: "contrast",
      value: 30,
    });
    state = editorReducer(state, {
      type: "save-start",
      idempotencyKey: "key-1",
      fingerprint: "fingerprint-1",
    });
    state = editorReducer(state, {
      type: "conflict",
      state: sessionState({
        recipe: withAdjustment(state.committed, "contrast", 55),
        revisionId: NEXT_REVISION_ID,
        revisionNo: 2,
        canUndo: true,
      }),
    });

    expect(state.draft.adjustments.contrast).toBe(30);
    expect(state.committed.adjustments.contrast).toBe(55);
    expect(state.activeRevisionId).toBe(NEXT_REVISION_ID);
    expect(state.save.status).toBe("unsaved");
    expect(state.save.idempotencyKey).toBeNull();
    expect(state.notice).toBe(CONFLICT_NOTICE);
  });

  it("reports disabled states for history controls", () => {
    const ready = readyEditorState(undefined, { canUndo: true, canRedo: false });
    expect(selectCanUndo(ready)).toBe(true);
    expect(selectCanRedo(ready)).toBe(false);
    expect(selectCanReset(ready)).toBe(false);

    const edited = editorReducer(ready, {
      type: "save-success",
      state: sessionState({
        recipe: withAdjustment(ready.draft, "temperature", 8),
        revisionId: NEXT_REVISION_ID,
        revisionNo: 2,
        canUndo: true,
      }),
    });
    expect(selectCanReset(edited)).toBe(true);

    const saving = editorReducer(edited, {
      type: "save-start",
      idempotencyKey: "key-2",
      fingerprint: "fingerprint-2",
    });
    expect(selectCanUndo(saving)).toBe(false);
    expect(selectCanRedo(saving)).toBe(false);
    expect(selectCanReset(saving)).toBe(false);
    expect(selectCanExport(saving)).toBe(true);

    const exporting = editorReducer(saving, { type: "export-start" });
    expect(exporting.phase).toBe("exporting");
    expect(editorReducer(exporting, { type: "export-finished" }).phase).toBe("ready");
  });
});
