import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { UseAnalysisResult } from "@/features/analysis/hooks/use-analysis";
import { PhotographerPanel } from "@/features/photographer/components/photographer-panel";
import type { EditorProposal } from "@/features/editor/state/editor-reducer";
import type { UsePhotographerChatResult } from "@/features/photographer/hooks/use-photographer-chat";
import type { UsePhotographerCritiqueResult } from "@/features/photographer/hooks/use-photographer-critique";
import type { UseFeedbackResult } from "@/features/photographer/hooks/use-feedback";
import type { UseStylesResult } from "@/features/photographer/hooks/use-styles";
import { normalizeRecipe } from "@/lib/recipe";
import type {
  CritiqueApplyResponse,
  PhotographerPatchResponse,
} from "@/types/photographer";
import { analysisReport } from "./analysis-fixtures";
import { feedbackState } from "./feedback-fixtures";
import { IMAGE_ID } from "./session-fixtures";
import {
  critiqueApply,
  noChangePlan,
  photographerCritique,
  photographerPatch,
  photographerPlan,
  styleCatalog,
  unsupportedPatch,
} from "./photographer-fixtures";

function analysisState(
  overrides: Partial<UseAnalysisResult> = {},
): UseAnalysisResult {
  return {
    analysisId: null,
    status: null,
    stage: null,
    isMock: false,
    report: null,
    error: null,
    requestPending: false,
    startedAt: null,
    running: false,
    start: vi.fn(),
    retry: vi.fn(),
    rerun: vi.fn(),
    ...overrides,
  };
}

function proposalState(
  overrides: Partial<EditorProposal> = {},
): EditorProposal {
  const plan = photographerPlan();
  return {
    status: "ready",
    source: "plan",
    view: "ai",
    plan,
    patch: null,
    recipe: normalizeRecipe(plan.recipe),
    error: null,
    accepting: false,
    ...overrides,
  };
}

function critiqueState(
  overrides: Partial<UsePhotographerCritiqueResult> = {},
): UsePhotographerCritiqueResult {
  return {
    critique: null,
    pending: false,
    applying: false,
    error: null,
    canRequest: true,
    canApply: true,
    request: vi.fn(async () => true),
    apply: vi.fn(async () => true),
    clear: vi.fn(),
    ...overrides,
  };
}

function stylesResult(
  overrides: Partial<UseStylesResult> = {},
): UseStylesResult {
  return {
    styles: styleCatalog(),
    loading: false,
    error: null,
    reload: vi.fn(),
    ...overrides,
  };
}

function chatState(
  overrides: Partial<UsePhotographerChatResult> = {},
): UsePhotographerChatResult {
  return {
    turns: [],
    pending: false,
    error: null,
    canSend: true,
    send: vi.fn(async () => true),
    reset: vi.fn(),
    ...overrides,
  };
}

/** The proposal slice as it looks after `patch-ready` lands a chat patch. */
function patchProposal(
  patch: PhotographerPatchResponse,
  overrides: Partial<EditorProposal> = {},
): EditorProposal {
  return proposalState({
    source: "chat",
    plan: null,
    patch,
    recipe: normalizeRecipe(patch.recipe),
    ...overrides,
  });
}

/** The proposal slice as it looks after `critique-ready` lands a preview. */
function critiqueProposal(
  patch: CritiqueApplyResponse = critiqueApply(),
  overrides: Partial<EditorProposal> = {},
): EditorProposal {
  return proposalState({
    source: "critique",
    plan: null,
    patch,
    recipe: normalizeRecipe(patch.recipe),
    ...overrides,
  });
}

function renderPanel(
  options: {
    analysis?: UseAnalysisResult;
    proposal?: EditorProposal;
    canAccept?: boolean;
    dirty?: boolean;
    styles?: UseStylesResult;
    chat?: UsePhotographerChatResult;
    critique?: UsePhotographerCritiqueResult;
    selectedStyleId?: string | null;
    styleStrength?: number;
    feedback?: UseFeedbackResult;
  } = {},
) {
  const handlers = {
    onClose: vi.fn(),
    onStart: vi.fn(),
    onRetry: vi.fn(),
    onCancel: vi.fn(),
    onView: vi.fn(),
    onAccept: vi.fn(),
    onAbandon: vi.fn(),
    onSelectStyle: vi.fn(),
    onStyleStrengthChange: vi.fn(),
    onStyleStrengthCommit: vi.fn(),
  };
  render(
    <PhotographerPanel
      open
      imageId={IMAGE_ID}
      analysis={options.analysis ?? analysisState()}
      proposal={
        options.proposal ??
        proposalState({
          status: "idle",
          source: null,
          plan: null,
          recipe: null,
        })
      }
      canAccept={options.canAccept ?? false}
      dirty={options.dirty ?? false}
      styles={options.styles ?? stylesResult()}
      chat={options.chat ?? chatState()}
      critique={options.critique ?? critiqueState()}
      selectedStyleId={options.selectedStyleId ?? null}
      styleStrength={options.styleStrength ?? 0.5}
      feedback={options.feedback ?? feedbackState()}
      {...handlers}
    />,
  );
  return handlers;
}

describe("PhotographerPanel", () => {
  it("starts the analysis-and-plan flow from the idle state", async () => {
    const handlers = renderPanel();

    expect(screen.getByText("尚未分析这张照片")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "开始自动优化" }));
    expect(handlers.onStart).toHaveBeenCalledTimes(1);
  });

  it("shows the real analysis stage without a fake percentage", () => {
    renderPanel({
      analysis: analysisState({
        status: "processing",
        stage: "vision",
        running: true,
      }),
    });

    expect(screen.getByText("正在理解照片并识别场景")).toBeInTheDocument();
    expect(
      screen.getByRole("progressbar", { name: "分析阶段进度" }),
    ).toHaveAttribute("aria-valuenow", "1");
    expect(
      screen.getByText("第 2/4 步 · 识别场景与主体"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/\d+\s*%/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "分析中，完成后自动生成方案" }),
    ).toBeDisabled();
  });

  it("shows loading state and lets the user cancel the plan request", async () => {
    const handlers = renderPanel({
      proposal: proposalState({ status: "loading", plan: null, recipe: null }),
    });

    expect(screen.getByText(/正在调用 Planner 并校验参数/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "取消生成" }));
    expect(handlers.onCancel).toHaveBeenCalledTimes(1);
  });

  it("shows a plan error with retry", async () => {
    const handlers = renderPanel({
      proposal: proposalState({
        status: "error",
        plan: null,
        recipe: null,
        error: {
          code: "photographer_timeout",
          message: "生成方案超时，请稍后重试。",
          details: {},
        },
      }),
    });

    expect(screen.getByText("生成方案超时，请稍后重试。")).toBeInTheDocument();
    expect(screen.getByText("photographer_timeout")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "重新生成方案" }));
    expect(handlers.onRetry).toHaveBeenCalledTimes(1);
  });

  it("renders an auditable plan with mock/degraded flags and change values", () => {
    renderPanel({
      proposal: proposalState({
        plan: photographerPlan({ degraded: true }),
      }),
      canAccept: true,
    });

    expect(
      screen.getByText("模拟方案（未调用真实 Planner 模型）"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("确定性回退方案（模型输出未通过校验）"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "自然平衡" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "已确认问题" }),
    ).toBeInTheDocument();
    expect(screen.getByText("光线平淡")).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "参数变化" }),
    ).toBeInTheDocument();
    expect(screen.getByText("对比度")).toBeInTheDocument();
    expect(screen.getByText("0 → 12")).toBeInTheDocument();
    expect(
      screen.getByText("本方案未使用局部蒙版；自动优化不会自行创建蒙版。"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "接受方案" })).toBeEnabled();
  });

  it("accepts, abandons, and switches between original and AI preview", async () => {
    const handlers = renderPanel({
      proposal: proposalState(),
      canAccept: true,
    });

    await userEvent.click(screen.getByRole("button", { name: "AI 方案预览" }));
    expect(handlers.onView).toHaveBeenCalledWith("ai");
    await userEvent.click(screen.getByRole("button", { name: "原图" }));
    expect(handlers.onView).toHaveBeenCalledWith("original");
    await userEvent.click(screen.getByRole("button", { name: "继续调整" }));
    expect(handlers.onView).toHaveBeenCalledWith("editor");

    await userEvent.click(screen.getByRole("button", { name: "接受方案" }));
    expect(handlers.onAccept).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: "放弃" }));
    expect(handlers.onAbandon).toHaveBeenCalledTimes(1);
  });

  it("disables accept when the plan changes nothing", () => {
    renderPanel({
      proposal: proposalState({
        plan: noChangePlan(),
        recipe: normalizeRecipe({}),
      }),
      canAccept: false,
    });

    expect(screen.getByText("当前照片无需主要调整")).toBeInTheDocument();
    expect(
      screen.getByText("当前照片无需主要调整，接受按钮已停用。"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "接受方案" })).toBeDisabled();
  });

  it("asks the user to save first when the draft is dirty", () => {
    renderPanel({
      proposal: proposalState(),
      canAccept: false,
      dirty: true,
    });

    expect(
      screen.getByText("有未保存的调整，请先保存或放弃后再接受 AI 方案。"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "接受方案" })).toBeDisabled();
  });

  it("surfaces analysis errors in the panel", () => {
    renderPanel({
      analysis: analysisState({
        status: "failed",
        stage: "failed",
        error: {
          code: "analysis_failed",
          message: "分析失败，请稍后重试。",
          requestId: null,
        },
      }),
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "分析失败，请稍后重试。",
    );
    expect(screen.getByRole("button", { name: "重新生成方案" })).toBeEnabled();
  });

  it("shows the analysis report state when the report already exists", () => {
    renderPanel({
      analysis: analysisState({
        status: "completed",
        stage: "completed",
        report: analysisReport(),
      }),
    });

    expect(screen.getByText("已有分析结果，可生成方案")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始自动优化" })).toBeEnabled();
  });
});

describe("PhotographerPanel style picker", () => {
  const withReport = analysisState({
    status: "completed",
    stage: "completed",
    report: analysisReport(),
  });

  it("groups the catalog into scene recommendations and other styles", () => {
    renderPanel({ analysis: withReport });

    expect(screen.getByText("场景推荐 · 人像")).toBeInTheDocument();
    expect(screen.getByText("其他风格")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "自动优化（不选风格）" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", { name: "自然人像" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "黑白纪实" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "风光" })).toBeInTheDocument();
  });

  it("falls back to one flat list before an analysis exists", () => {
    renderPanel();

    expect(screen.queryByText("场景推荐 · 人像")).not.toBeInTheDocument();
    expect(screen.getByText("其他风格")).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: /人像|风光|街头|纪实|叙事/ }),
    ).toHaveLength(6);
  });

  it("selects a style and reports the full definition", async () => {
    const handlers = renderPanel({ analysis: withReport });

    await userEvent.click(screen.getByRole("button", { name: "黑白纪实" }));

    expect(handlers.onSelectStyle).toHaveBeenCalledWith(
      expect.objectContaining({ id: "monochrome", defaultStrength: 0.7 }),
    );
  });

  it("renders the selected style as parameterized metadata", () => {
    renderPanel({
      analysis: withReport,
      selectedStyleId: "monochrome",
      styleStrength: 0.7,
    });

    expect(screen.getByText("黑白纪实 v1.0 · 强度 70%")).toBeInTheDocument();
    expect(
      screen.getByText("完全去饱和，只用影调关系重建画面。"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/风格由参数组合实时计算，不依赖 LUT/),
    ).toBeInTheDocument();
    const slider = screen.getByRole("slider", { name: "风格强度" });
    expect(slider).toHaveValue("0.7");
    expect(slider).toHaveAttribute("aria-valuetext", "70%");
    expect(
      screen.getByRole("button", { name: "生成风格方案" }),
    ).toBeInTheDocument();
  });

  it("reports zero strength as an un-stylized plan", () => {
    renderPanel({
      analysis: withReport,
      selectedStyleId: "portrait",
      styleStrength: 0,
    });

    expect(screen.getByText(/强度 0 时不叠加任何风格参数/)).toBeInTheDocument();
  });

  it("submits the strength only when the slider is released", () => {
    const handlers = renderPanel({
      analysis: withReport,
      selectedStyleId: "portrait",
      styleStrength: 0.5,
    });
    const slider = screen.getByRole("slider", { name: "风格强度" });

    fireEvent.change(slider, { target: { value: "0.8" } });
    expect(handlers.onStyleStrengthChange).toHaveBeenCalledWith(0.8);
    expect(handlers.onStyleStrengthCommit).not.toHaveBeenCalled();

    fireEvent.focusOut(slider);
    expect(handlers.onStyleStrengthCommit).toHaveBeenCalledTimes(1);

    fireEvent.keyUp(slider, { key: "ArrowRight" });
    expect(handlers.onStyleStrengthCommit).toHaveBeenCalledTimes(2);
  });

  it("shows the applied style metadata on a generated plan", () => {
    renderPanel({
      analysis: withReport,
      proposal: proposalState({
        plan: photographerPlan({
          mode: "style",
          styleId: "monochrome",
          styleVersion: "1.0",
          styleStrength: 0.8,
        }),
      }),
      selectedStyleId: "monochrome",
      styleStrength: 0.8,
      canAccept: true,
    });

    expect(
      screen.getByText(/风格 monochrome v1\.0 · 强度 80%/),
    ).toBeInTheDocument();
    expect(screen.getByText(/参数化实现，非 LUT/)).toBeInTheDocument();
  });

  it("keeps the picker quiet while the catalog loads", () => {
    renderPanel({
      analysis: withReport,
      styles: stylesResult({ styles: [], loading: true }),
    });

    expect(screen.getByText("风格库加载中…")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "自动优化（不选风格）" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始自动优化" })).toBeEnabled();
  });

  it("offers a retry when the catalog cannot be loaded", async () => {
    const reload = vi.fn();
    const handlers = renderPanel({
      analysis: withReport,
      styles: stylesResult({
        styles: [],
        error: {
          code: "network_error",
          message: "无法连接后端服务。",
          details: {},
        },
        reload,
      }),
    });

    expect(screen.getByText("无法连接后端服务。")).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "重新加载风格库" }),
    );
    expect(reload).toHaveBeenCalledTimes(1);
    expect(handlers.onStart).not.toHaveBeenCalled();
  });
});

describe("PhotographerPanel chat adjustments", () => {
  it("submits a typed instruction on Enter and clears the composer", async () => {
    const chat = chatState();
    renderPanel({ chat });
    const composer = screen.getByRole("textbox", { name: "调整指令" });

    await userEvent.type(composer, "降低一点饱和度");
    await userEvent.keyboard("{Enter}");

    expect(chat.send).toHaveBeenCalledWith("降低一点饱和度");
    expect(composer).toHaveValue("");
  });

  it("keeps Shift+Enter as a newline instead of sending", async () => {
    const chat = chatState();
    renderPanel({ chat });
    const composer = screen.getByRole("textbox", { name: "调整指令" });

    await userEvent.type(composer, "第一行{shift>}{Enter}{/shift}第二行");

    expect(chat.send).not.toHaveBeenCalled();
    expect(composer).toHaveValue("第一行\n第二行");
  });

  it("sends a quick prompt without typing", async () => {
    const chat = chatState();
    renderPanel({ chat });

    await userEvent.click(screen.getByRole("button", { name: "电影感一点" }));

    expect(chat.send).toHaveBeenCalledWith("电影感一点");
  });

  it("refuses to send while the chat has no anchor", async () => {
    const chat = chatState({ canSend: false });
    renderPanel({ chat });

    expect(
      screen.getByText(
        "需要当前会话与这张照片的分析结果才能对话调整；先运行分析或生成方案。",
      ),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "降低饱和度" }));
    expect(chat.send).not.toHaveBeenCalled();
  });

  it("marks the composer busy while a patch is being generated", () => {
    renderPanel({ chat: chatState({ pending: true, canSend: false }) });

    expect(screen.getByRole("button", { name: "正在调整…" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "调整指令" })).toBeDisabled();
  });

  it("renders only the parameters a patch moved, with evidence-free reasons", () => {
    renderPanel({
      proposal: patchProposal(
        photographerPatch({
          warnings: ["饱和度已按指令收紧到安全范围。"],
          limitations: ["不会改动你已有的曲线与色彩分级。"],
        }),
      ),
      canAccept: true,
    });

    expect(
      screen.getByRole("heading", { name: "对话调整建议" }),
    ).toBeInTheDocument();
    expect(screen.getByText("1 项参数变化")).toBeInTheDocument();
    expect(
      screen.getByText("只移动了饱和度这一个参数，其他调整保持原样。"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "参数变化" }),
    ).toBeInTheDocument();
    expect(screen.getByText("饱和度")).toBeInTheDocument();
    expect(screen.getByText("0 → -8")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "提示" })).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "能力限制" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "自然平衡" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "接受方案" })).toBeEnabled();
  });

  it("labels a local patch with the mask it belongs to", () => {
    renderPanel({
      proposal: patchProposal(
        photographerPatch({
          changes: [
            {
              path: "localAdjustments.mask_person.exposureEv",
              previous: 0,
              proposed: 0.3,
              reason: "按指令调整局部曝光。",
              evidenceRefs: ["instruction"],
            },
          ],
        }),
      ),
    });

    expect(screen.getByText("局部 mask_person · 曝光")).toBeInTheDocument();
  });

  it("keeps an unsupported instruction as a boundary note with no recipe change", () => {
    renderPanel({
      proposal: patchProposal(unsupportedPatch()),
      canAccept: false,
    });

    expect(
      screen.getByRole("heading", { name: "这项调整不支持" }),
    ).toBeInTheDocument();
    expect(screen.getByText("配方未变化")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "当前配方未发生变化，画面保持你已有的调整。",
    );
    expect(
      screen.getByText(/不支持：删除或移动画面中的物体/),
    ).toBeInTheDocument();
    expect(
      screen.getByText("这条指令没有产生参数变化，接受按钮已停用。"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "接受方案" })).toBeDisabled();
  });

  it("keeps the transcript visible and lets the user clear it", async () => {
    const chat = chatState({
      turns: [
        {
          id: "turn-1",
          instruction: "降低饱和度",
          reply: "只移动了饱和度这一个参数。",
          pending: false,
          failed: false,
        },
        {
          id: "turn-2",
          instruction: "删除背景里的人物",
          reply: null,
          pending: false,
          failed: true,
        },
      ],
      error: {
        code: "network_error",
        message: "无法连接后端服务。",
        details: {},
      },
    });
    renderPanel({ chat });

    expect(screen.getByRole("list", { name: "对话记录" })).toBeInTheDocument();
    const transcript = within(screen.getByRole("list", { name: "对话记录" }));
    expect(transcript.getByText("降低饱和度")).toBeInTheDocument();
    expect(
      transcript.getByText("只移动了饱和度这一个参数。"),
    ).toBeInTheDocument();
    expect(transcript.getByText("删除背景里的人物")).toBeInTheDocument();
    expect(transcript.getByText("无法连接后端服务。")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "清空对话" }));
    expect(chat.reset).toHaveBeenCalledTimes(1);
  });

  it("shares the preview and accept controls with plan proposals", async () => {
    const handlers = renderPanel({
      proposal: patchProposal(photographerPatch()),
      canAccept: true,
    });

    await userEvent.click(screen.getByRole("button", { name: "原图" }));
    expect(handlers.onView).toHaveBeenCalledWith("original");
    await userEvent.click(screen.getByRole("button", { name: "接受方案" }));
    expect(handlers.onAccept).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "放弃" }));
    expect(handlers.onAbandon).toHaveBeenCalledTimes(1);
  });

  it("asks for a save before accepting a patch over a dirty draft", () => {
    renderPanel({
      proposal: patchProposal(photographerPatch()),
      canAccept: true,
      dirty: true,
    });

    expect(
      screen.getByText("有未保存的调整，请先保存或放弃后再接受 AI 方案。"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "接受方案" })).toBeDisabled();
  });
});

describe("PhotographerPanel critique", () => {
  it("offers a deterministic entry point before a critique exists", async () => {
    const critique = critiqueState();
    renderPanel({ critique });

    const section = screen.getByRole("region", { name: "AI 摄影点评" });
    expect(within(section).getByText("规则生成")).toBeInTheDocument();
    const button = within(section).getByRole("button", {
      name: "生成摄影点评",
    });
    expect(button).toBeEnabled();

    await userEvent.click(button);
    expect(critique.request).toHaveBeenCalledTimes(1);
  });

  it("says why the critique is unavailable without an analysis", () => {
    renderPanel({ critique: critiqueState({ canRequest: false }) });

    const section = screen.getByRole("region", { name: "AI 摄影点评" });
    expect(
      within(section).getByRole("button", { name: "生成摄影点评" }),
    ).toBeDisabled();
    expect(
      within(section).getByText(
        "需要先完成这张照片的 AI 摄影分析，点评才有依据。",
      ),
    ).toBeInTheDocument();
  });

  it("labels a critique that is still being generated", () => {
    renderPanel({ critique: critiqueState({ pending: true, canRequest: false }) });

    expect(
      screen.getByRole("button", { name: "正在生成点评…" }),
    ).toBeDisabled();
  });

  it("renders every conclusion with its own evidence disclosure", () => {
    renderPanel({ critique: critiqueState({ critique: photographerCritique() }) });

    for (const title of ["优点", "技术观测", "可能的问题", "创作解读"]) {
      expect(
        screen.getByRole("region", { name: title }),
      ).toBeInTheDocument();
    }
    expect(
      screen.getByText("本次点评基于模拟分析结果（未调用真实视觉模型）"),
    ).toBeInTheDocument();

    const issues = within(screen.getByRole("region", { name: "可能的问题" }));
    expect(
      issues.getByText("高光溢出（高，置信度 85%）：高光裁切占比 4.2%；测量值支持该判断。"),
    ).toBeInTheDocument();
    const disclosure = issues.getByText("证据 2 项").closest("details");
    expect(disclosure).not.toBeNull();
    expect(within(disclosure as HTMLElement).getByText("issue_hl")).toBeInTheDocument();

    fireEvent.click(issues.getByText("证据 2 项"));
    expect(
      (issues.getByText("证据 2 项").closest("details") as HTMLDetailsElement).open,
    ).toBe(true);
  });

  it("marks creative readings as subjective instead of fact", () => {
    renderPanel({ critique: critiqueState({ critique: photographerCritique() }) });

    const creative = within(screen.getByRole("region", { name: "创作解读" }));
    expect(creative.getByText("主观")).toBeInTheDocument();
    expect(
      creative.getByText("逆光带来的轮廓可能是这张照片的情绪来源。"),
    ).toBeInTheDocument();
    // The measured sections stay unlabelled: they are not opinions.
    expect(
      within(screen.getByRole("region", { name: "技术观测" })).queryByText("主观"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "点评局限" }),
    ).toBeInTheDocument();
  });

  it("routes only parameter-bearing suggestions to the editor", async () => {
    const critique = critiqueState({ critique: photographerCritique() });
    renderPanel({ critique });

    const suggestions = within(screen.getByRole("region", { name: "后期建议" }));
    expect(suggestions.getAllByText("应用到编辑")).toHaveLength(1);
    expect(
      suggestions.getByText(
        "这条建议不涉及可调参数，需要通过裁切或拍摄时机实现。",
      ),
    ).toBeInTheDocument();

    await userEvent.click(suggestions.getByText("应用到编辑"));
    expect(critique.apply).toHaveBeenCalledTimes(1);
    expect(vi.mocked(critique.apply).mock.calls[0][0]).toMatchObject({
      category: "exposure",
      recipePatch: { highlights: -20, whites: -8 },
    });
  });

  it("disables the apply entry while the preview is busy", () => {
    renderPanel({
      critique: critiqueState({
        critique: photographerCritique(),
        applying: true,
        canApply: false,
      }),
    });

    const suggestions = within(screen.getByRole("region", { name: "后期建议" }));
    expect(suggestions.getByText("正在生成预览…")).toBeDisabled();
  });

  it("previews a critique suggestion through the shared review controls", async () => {
    const handlers = renderPanel({
      proposal: critiqueProposal(),
      canAccept: true,
      critique: critiqueState({ critique: photographerCritique() }),
    });

    expect(
      screen.getByRole("heading", { name: "点评建议预览" }),
    ).toBeInTheDocument();
    expect(screen.getByText("2 项参数变化")).toBeInTheDocument();
    // Only the two parameters the suggestion moved are listed as changes.
    expect(screen.queryByText("对比度")).not.toBeInTheDocument();
    expect(screen.getByText("高光")).toBeInTheDocument();
    expect(screen.getByText("白色色阶")).toBeInTheDocument();
    expect(screen.getByText("0 → -20")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "原图" }));
    expect(handlers.onView).toHaveBeenCalledWith("original");
    await userEvent.click(screen.getByRole("button", { name: "接受方案" }));
    expect(handlers.onAccept).toHaveBeenCalledTimes(1);
  });

  it("keeps a parameterless critique suggestion out of the accept path", () => {
    renderPanel({
      proposal: critiqueProposal(
        critiqueApply({ changes: [], recipe: normalizeRecipe({}) }),
      ),
      canAccept: false,
    });

    expect(screen.getByText("0 项参数变化")).toBeInTheDocument();
    expect(
      screen.getByText("这条点评建议没有产生参数变化，接受按钮已停用。"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "接受方案" })).toBeDisabled();
  });

  it("regenerates and collapses a critique", async () => {
    const critique = critiqueState({ critique: photographerCritique() });
    renderPanel({ critique });

    await userEvent.click(screen.getByRole("button", { name: "重新生成点评" }));
    expect(critique.request).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "收起点评" }));
    expect(critique.clear).toHaveBeenCalledTimes(1);
  });

  it("surfaces a critique failure without hiding the entry point", () => {
    renderPanel({
      critique: critiqueState({
        error: {
          code: "provider_unavailable",
          message: "点评服务暂不可用。",
          details: {},
        },
      }),
    });

    expect(screen.getByRole("alert")).toHaveTextContent("点评服务暂不可用。");
    expect(screen.getByRole("button", { name: "生成摄影点评" })).toBeEnabled();
  });
});
