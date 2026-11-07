import { describe, expect, it } from "vitest";

import {
  editorReducer,
  isChatPatch,
  selectCanAcceptProposal,
  selectProposalAnchorId,
  selectProposalChanges,
  selectProposalPreviewing,
  selectProposalRecipe,
} from "@/features/editor/state/editor-reducer";
import { DEFAULT_ADJUSTMENTS, normalizeRecipe } from "@/lib/recipe";
import {
  NEXT_REVISION_ID,
  readyEditorState,
  sessionState,
} from "./session-fixtures";
import {
  critiqueApply,
  PATCH_ID,
  PLAN_ID,
  photographerPatch,
  photographerPlan,
  unsupportedPatch,
} from "./photographer-fixtures";

describe("editorReducer proposal state", () => {
  it("stores a proposal without touching draft, committed, or save state", () => {
    const ready = readyEditorState();
    const next = editorReducer(ready, {
      type: "proposal-ready",
      plan: photographerPlan(),
    });

    expect(next.proposal.status).toBe("ready");
    expect(next.proposal.view).toBe("ai");
    expect(next.draft).toBe(ready.draft);
    expect(next.committed).toBe(ready.committed);
    expect(next.save).toBe(ready.save);
    expect(selectProposalPreviewing(next)).toBe(true);
    expect(selectProposalRecipe(next)?.adjustments.contrast).toBe(12);
    expect(selectCanAcceptProposal(next)).toBe(true);
  });

  it("previews the proposal recipe independently of the draft", () => {
    const next = editorReducer(readyEditorState(), {
      type: "proposal-ready",
      plan: photographerPlan(),
    });
    const editing = editorReducer(next, {
      type: "proposal-view",
      view: "editor",
    });

    expect(selectProposalRecipe(editing)).toBeNull();
    expect(selectProposalPreviewing(editing)).toBe(false);
    expect(editing.draft.adjustments.contrast).toBe(0);

    const original = editorReducer(next, {
      type: "proposal-view",
      view: "original",
    });
    expect(original.proposal.view).toBe("original");
    expect(selectProposalRecipe(original)).toBeNull();
  });

  it("does not let a proposal make the draft dirty or editable", () => {
    const next = editorReducer(readyEditorState(), {
      type: "proposal-ready",
      plan: photographerPlan(),
    });
    const adjusted = editorReducer(next, {
      type: "draft-adjustment",
      key: "contrast",
      value: 30,
    });

    expect(adjusted.draft.adjustments.contrast).toBe(30);
    expect(adjusted.committed.adjustments.contrast).toBe(0);
    expect(adjusted.proposal.status).toBe("ready");
    expect(selectCanAcceptProposal(adjusted)).toBe(false);
  });

  it("clears the proposal when a revision is saved", () => {
    const withProposal = editorReducer(readyEditorState(), {
      type: "proposal-ready",
      plan: photographerPlan(),
    });
    const saved = editorReducer(withProposal, {
      type: "save-success",
      state: sessionState({
        recipe: normalizeRecipe({
          adjustments: { ...DEFAULT_ADJUSTMENTS, contrast: 12 },
        }),
        revisionId: NEXT_REVISION_ID,
        revisionNo: 2,
        canUndo: true,
      }),
    });

    expect(saved.proposal.status).toBe("idle");
    expect(saved.proposal.plan).toBeNull();
    expect(saved.committed.adjustments.contrast).toBe(12);
  });

  it("applies the accepted revision and clears the proposal", () => {
    const withProposal = editorReducer(readyEditorState(), {
      type: "proposal-ready",
      plan: photographerPlan(),
    });
    const accepting = editorReducer(withProposal, {
      type: "proposal-accepting",
    });
    expect(accepting.proposal.accepting).toBe(true);

    const accepted = editorReducer(accepting, {
      type: "proposal-accepted",
      state: sessionState({
        recipe: normalizeRecipe({
          adjustments: { ...DEFAULT_ADJUSTMENTS, contrast: 12 },
        }),
        revisionId: NEXT_REVISION_ID,
        revisionNo: 2,
        source: "ai",
        canUndo: true,
      }),
    });

    expect(accepted.activeRevisionId).toBe(NEXT_REVISION_ID);
    expect(accepted.committed.adjustments.contrast).toBe(12);
    expect(accepted.draft.adjustments.contrast).toBe(12);
    expect(accepted.proposal.status).toBe("idle");
    expect(accepted.proposal.accepting).toBe(false);
    expect(accepted.save.status).toBe("saved");
  });

  it("keeps a failed acceptance visible for retry", () => {
    const withProposal = editorReducer(readyEditorState(), {
      type: "proposal-ready",
      plan: photographerPlan(),
    });
    const accepting = editorReducer(withProposal, {
      type: "proposal-accepting",
    });
    const failed = editorReducer(accepting, {
      type: "proposal-accept-failed",
      error: {
        code: "storage_error",
        message: "服务保存数据失败，请稍后重试。",
        details: {},
      },
    });

    expect(failed.proposal.status).toBe("ready");
    expect(failed.proposal.accepting).toBe(false);
    expect(failed.proposal.error?.code).toBe("storage_error");
    expect(failed.activeRevisionId).toBe(withProposal.activeRevisionId);
  });

  it("clears a proposal on error or explicit abandon", () => {
    const withProposal = editorReducer(readyEditorState(), {
      type: "proposal-ready",
      plan: photographerPlan(),
    });
    const failed = editorReducer(withProposal, {
      type: "proposal-error",
      error: { code: "photographer_timeout", message: "超时", details: {} },
    });
    expect(failed.proposal.status).toBe("error");
    expect(failed.proposal.plan).toBeNull();

    const cleared = editorReducer(withProposal, { type: "proposal-clear" });
    expect(cleared.proposal.status).toBe("idle");
    expect(cleared.proposal.plan).toBeNull();
  });
});

describe("editorReducer chat patch state", () => {
  it("stores a patch as the only candidate and previews its recipe", () => {
    const ready = readyEditorState();
    const next = editorReducer(ready, {
      type: "patch-ready",
      patch: photographerPatch(),
    });

    expect(next.proposal.status).toBe("ready");
    expect(next.proposal.source).toBe("chat");
    expect(next.proposal.view).toBe("ai");
    expect(next.proposal.plan).toBeNull();
    expect(next.proposal.patch?.patchId).toBe(PATCH_ID);
    expect(selectProposalRecipe(next)?.adjustments.saturation).toBe(-8);
    expect(selectProposalPreviewing(next)).toBe(true);
    expect(selectProposalChanges(next.proposal)).toHaveLength(1);
    expect(selectCanAcceptProposal(next)).toBe(true);
    expect(next.draft).toBe(ready.draft);
    expect(next.committed).toBe(ready.committed);
    expect(next.save).toBe(ready.save);
  });

  it("anchors the next instruction on the newest plan or patch", () => {
    const withPlan = editorReducer(readyEditorState(), {
      type: "proposal-ready",
      plan: photographerPlan(),
    });
    expect(selectProposalAnchorId(withPlan.proposal)).toBe(PLAN_ID);

    const withPatch = editorReducer(withPlan, {
      type: "patch-ready",
      patch: photographerPatch(),
    });
    expect(withPatch.proposal.plan).toBeNull();
    expect(selectProposalAnchorId(withPatch.proposal)).toBe(PATCH_ID);

    const replanned = editorReducer(withPatch, {
      type: "proposal-ready",
      plan: photographerPlan(),
    });
    expect(replanned.proposal.patch).toBeNull();
    expect(selectProposalAnchorId(replanned.proposal)).toBe(PLAN_ID);
  });

  it("keeps a multi-turn chain on the latest patch, not the original plan", () => {
    const first = editorReducer(readyEditorState(), {
      type: "patch-ready",
      patch: photographerPatch({
        changes: [
          {
            path: "adjustments.saturation",
            previous: 0,
            proposed: -8,
            reason: "按指令调整饱和度。",
            evidenceRefs: ["instruction"],
          },
        ],
      }),
    });
    const second = editorReducer(first, {
      type: "patch-ready",
      patch: photographerPatch({
        patchId: "66666666-6666-4666-6666-666666666666",
        recipe: normalizeRecipe({
          adjustments: {
            ...DEFAULT_ADJUSTMENTS,
            saturation: -8,
            contrast: 10,
          },
        }),
        changes: [
          {
            path: "adjustments.contrast",
            previous: 0,
            proposed: 10,
            reason: "按指令调整对比度。",
            evidenceRefs: ["instruction"],
          },
        ],
      }),
    });

    expect(selectProposalAnchorId(second.proposal)).toBe(
      "66666666-6666-4666-6666-666666666666",
    );
    expect(second.proposal.recipe?.adjustments.saturation).toBe(-8);
    expect(second.proposal.recipe?.adjustments.contrast).toBe(10);
  });

  it("refuses to accept a patch that changed nothing", () => {
    const next = editorReducer(readyEditorState(), {
      type: "patch-ready",
      patch: unsupportedPatch(),
    });

    const refused = next.proposal.patch;
    expect(refused !== null && isChatPatch(refused) && !refused.supported).toBe(
      true,
    );
    expect(selectProposalChanges(next.proposal)).toHaveLength(0);
    expect(selectCanAcceptProposal(next)).toBe(false);
    expect(selectProposalAnchorId(next.proposal)).toBe(PATCH_ID);
  });

  it("does not let a patch dirty the draft", () => {
    const withPatch = editorReducer(readyEditorState(), {
      type: "patch-ready",
      patch: photographerPatch(),
    });
    const adjusted = editorReducer(withPatch, {
      type: "draft-adjustment",
      key: "saturation",
      value: 30,
    });

    expect(adjusted.draft.adjustments.saturation).toBe(30);
    expect(adjusted.committed.adjustments.saturation).toBe(0);
    expect(adjusted.proposal.status).toBe("ready");
    expect(selectCanAcceptProposal(adjusted)).toBe(false);
  });

  it("clears the patch once the accepted revision lands", () => {
    const withPatch = editorReducer(readyEditorState(), {
      type: "patch-ready",
      patch: photographerPatch(),
    });
    const accepted = editorReducer(
      editorReducer(withPatch, { type: "proposal-accepting" }),
      {
        type: "proposal-accepted",
        state: sessionState({
          recipe: normalizeRecipe({
            adjustments: { ...DEFAULT_ADJUSTMENTS, saturation: -8 },
          }),
          revisionId: NEXT_REVISION_ID,
          revisionNo: 2,
          source: "ai",
          canUndo: true,
        }),
      },
    );

    expect(accepted.committed.adjustments.saturation).toBe(-8);
    expect(accepted.draft.adjustments.saturation).toBe(-8);
    expect(accepted.proposal.patch).toBeNull();
    expect(accepted.proposal.source).toBeNull();
    expect(selectProposalAnchorId(accepted.proposal)).toBeNull();
  });

  it("drops the patch on abandon and on a failed send", () => {
    const withPatch = editorReducer(readyEditorState(), {
      type: "patch-ready",
      patch: photographerPatch(),
    });

    const cleared = editorReducer(withPatch, { type: "proposal-clear" });
    expect(cleared.proposal.patch).toBeNull();
    expect(selectProposalAnchorId(cleared.proposal)).toBeNull();

    const failed = editorReducer(withPatch, {
      type: "proposal-error",
      error: { code: "network_error", message: "网络错误", details: {} },
    });
    expect(failed.proposal.status).toBe("error");
    expect(failed.proposal.patch).toBeNull();
  });
});

describe("editorReducer critique preview state", () => {
  it("previews a critique patch without touching draft or save state", () => {
    const ready = readyEditorState();
    const next = editorReducer(ready, {
      type: "critique-ready",
      patch: critiqueApply(),
    });

    expect(next.proposal.status).toBe("ready");
    expect(next.proposal.source).toBe("critique");
    expect(next.proposal.plan).toBeNull();
    expect(selectProposalRecipe(next)?.adjustments.highlights).toBe(-20);
    expect(selectProposalChanges(next.proposal)).toHaveLength(2);
    expect(selectCanAcceptProposal(next)).toBe(true);
    expect(next.draft).toBe(ready.draft);
    expect(next.committed).toBe(ready.committed);
    expect(next.save).toBe(ready.save);
  });

  it("never anchors a follow-up instruction on a critique preview", () => {
    const next = editorReducer(readyEditorState(), {
      type: "critique-ready",
      patch: critiqueApply(),
    });

    // The id is only usable by a persisted plan/patch, so a chat turn would 404.
    expect(selectProposalAnchorId(next.proposal)).toBeNull();

    const withPlan = editorReducer(next, {
      type: "proposal-ready",
      plan: photographerPlan(),
    });
    expect(withPlan.proposal.patch).toBeNull();
    expect(selectProposalAnchorId(withPlan.proposal)).toBe(PLAN_ID);
  });

  it("refuses to accept a critique suggestion that changed nothing", () => {
    const next = editorReducer(readyEditorState(), {
      type: "critique-ready",
      patch: critiqueApply({ changes: [], recipe: normalizeRecipe({}) }),
    });

    expect(next.proposal.status).toBe("ready");
    expect(selectProposalChanges(next.proposal)).toHaveLength(0);
    expect(selectCanAcceptProposal(next)).toBe(false);
  });

  it("clears the critique preview on abandon and on a failed apply", () => {
    const next = editorReducer(readyEditorState(), {
      type: "critique-ready",
      patch: critiqueApply(),
    });

    const cleared = editorReducer(next, { type: "proposal-clear" });
    expect(cleared.proposal.patch).toBeNull();
    expect(cleared.proposal.source).toBeNull();

    const failed = editorReducer(next, {
      type: "proposal-error",
      error: {
        code: "photographer_recipe_invalid",
        message: "调整后的配方未通过校验。",
        details: {},
      },
    });
    expect(failed.proposal.status).toBe("error");
    expect(failed.proposal.patch).toBeNull();
  });

  it("accepts a critique preview as an ai revision like any other proposal", () => {
    const next = editorReducer(readyEditorState(), {
      type: "critique-ready",
      patch: critiqueApply(),
    });
    const accepted = editorReducer(
      editorReducer(next, { type: "proposal-accepting" }),
      {
        type: "proposal-accepted",
        state: sessionState({
          recipe: normalizeRecipe({
            adjustments: { ...DEFAULT_ADJUSTMENTS, highlights: -20, whites: -8 },
          }),
          revisionId: NEXT_REVISION_ID,
          revisionNo: 2,
          source: "ai",
          canUndo: true,
        }),
      },
    );

    expect(accepted.committed.adjustments.highlights).toBe(-20);
    expect(accepted.draft.adjustments.whites).toBe(-8);
    expect(accepted.proposal.status).toBe("idle");
    expect(accepted.proposal.source).toBeNull();
  });
});
