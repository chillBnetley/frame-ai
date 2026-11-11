import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreativeStudio } from "@/features/generative/studio/creative-studio";
import { buildStyleInstruction } from "@/features/generative/style-instruction";
import { ApiClientError } from "@/lib/api/client";
import * as generativeApi from "@/lib/api/generative";
import * as personalStyleApi from "@/lib/api/personal-style";
import type {
  GenerativeCapabilitiesResponse,
  GenerativeMaskView,
  GenerativeResultView,
  GenerativeStorageResponse,
  GenerativeTaskCreated,
  GenerativeTaskStatusResponse,
} from "@/types/generative";
import type { SessionState } from "@/types/session";
import type { AnalysisReport } from "@/types/analysis";
import { analysisReport } from "./analysis-fixtures";
import { PERSONAL_STYLE_ID, personalStyleItem } from "./personal-style-fixtures";

vi.mock("@/lib/api/personal-style", () => ({
  listPersonalStyles: vi.fn(),
}));

vi.mock("@/lib/api/generative", () => ({
  getGenerativeCapabilities: vi.fn(),
  getGenerativeStorage: vi.fn(),
  listGenerativeMasks: vi.fn(),
  createGenerativeMask: vi.fn(),
  createGenerativeTask: vi.fn(),
  getGenerativeTask: vi.fn(),
  cancelGenerativeTask: vi.fn(),
  retryGenerativeTask: vi.fn(),
  pollGenerativeTask: vi.fn(),
  acceptGenerativeResult: vi.fn(),
  rejectGenerativeResult: vi.fn(),
  generativeMaskImageUrl: vi.fn((id: string) => `/api/v1/generative/masks/${id}/image`),
  generativeResultImageUrl: vi.fn((id: string) => `/api/v1/generative/results/${id}/image`),
}));

const mockGetCapabilities = vi.mocked(generativeApi.getGenerativeCapabilities);
const mockGetStorage = vi.mocked(generativeApi.getGenerativeStorage);
const mockListMasks = vi.mocked(generativeApi.listGenerativeMasks);
const mockCreateMask = vi.mocked(generativeApi.createGenerativeMask);
const mockCreateTask = vi.mocked(generativeApi.createGenerativeTask);
const mockPollTask = vi.mocked(generativeApi.pollGenerativeTask);
const mockAcceptResult = vi.mocked(generativeApi.acceptGenerativeResult);
const mockRejectResult = vi.mocked(generativeApi.rejectGenerativeResult);
const mockCancelTask = vi.mocked(generativeApi.cancelGenerativeTask);
const mockRetryTask = vi.mocked(generativeApi.retryGenerativeTask);
const mockListStyles = vi.mocked(personalStyleApi.listPersonalStyles);

const MOCK_CAPABILITIES: GenerativeCapabilitiesResponse = {
  provider: "mock",
  model: "generative-mock-1",
  isMock: true,
  supportedTaskTypes: ["outpaint", "remove", "local_edit"],
  supportsMask: true,
  supportsMultipleOutputs: false,
  maxOutputPixels: 24_000_000,
  maxLongEdge: 8192,
  allowedOutputFormats: ["png"],
  declaredRetention: "Mock provider",
  notes: [],
};

const MOCK_STORAGE: GenerativeStorageResponse = {
  usedBytes: 10 * 1024 * 1024,
  limitBytes: 2048 * 1024 * 1024,
  assetBytes: 8 * 1024 * 1024,
  resultBytes: 2 * 1024 * 1024,
  maskBytes: 0,
  retentionDays: 7,
};

function mask(maskId: string, kind: GenerativeMaskView["kind"]): GenerativeMaskView {
  return {
    maskId,
    imageId: "img-001",
    baseGeneratedAssetId: null,
    kind,
    source: "user",
    coordinateSpace: "base-normalized",
    width: 800,
    height: 600,
    imageUrl: `/api/v1/generative/masks/${maskId}/image`,
    sha256: "0".repeat(64),
    feather: 2,
    inverted: false,
    quality: { coverage: 0.05, componentCount: 1, touchesBorder: false, warnings: [] },
    definition: { strokes: [], expand: 0 },
    createdAt: "2026-11-10T12:00:00Z",
  };
}

const MOCK_TASK_CREATED: GenerativeTaskCreated = {
  taskId: "task-001",
  status: "queued",
  stage: "queued",
  deduplicated: false,
  isMock: true,
  provider: "mock",
  model: "mock-1",
  expiresAt: "2026-11-11T00:00:00Z",
};

const MOCK_TASK_PROCESSING: GenerativeTaskStatusResponse = {
  taskId: "task-001",
  taskType: "outpaint",
  baseMode: "base",
  status: "processing",
  stage: "submitting",
  instruction: "",
  isMock: true,
  provider: "mock",
  model: "mock-1",
  attempts: 1,
  maxAttempts: 2,
  cancelRequested: false,
  createdAt: "2026-11-10T12:00:00Z",
  updatedAt: "2026-11-10T12:00:02Z",
  expiresAt: "2026-11-11T00:00:00Z",
};

const MOCK_CANDIDATE: GenerativeResultView = {
  resultId: "res-001",
  resultIndex: 0,
  status: "candidate",
  width: 1067,
  height: 600,
  imageUrl: "/api/v1/generative/results/res-001/image",
  warnings: ["mock_output"],
  createdAt: "2026-11-10T12:00:05Z",
};

const MOCK_TASK_SUCCEEDED: GenerativeTaskStatusResponse = {
  ...MOCK_TASK_PROCESSING,
  status: "succeeded",
  stage: "completed",
  results: [MOCK_CANDIDATE],
};

const MOCK_TASK_FAILED: GenerativeTaskStatusResponse = {
  ...MOCK_TASK_PROCESSING,
  status: "failed",
  stage: "failed",
  error: { code: "generative_blank_output", message: "生成结果为空白画面。" },
};

const MOCK_SESSION_STATE: SessionState = {
  sessionId: "sess-123",
  imageId: "img-001",
  activeRevisionId: "rev-3",
  headRevisionId: "rev-3",
  canUndo: true,
  canRedo: false,
  revision: {
    id: "rev-3",
    revisionNo: 3,
    parentId: "rev-2",
    source: "ai",
    recipe: {
      schemaVersion: "2.0",
      styleId: "natural",
      styleStrength: 0,
      masks: [],
      localAdjustments: [],
    },
    baseGeneratedAssetId: "asset-001",
    baseWidth: 800,
    baseHeight: 600,
    generativeTaskId: "task-001",
    createdAt: "2026-11-10T12:00:05Z",
  },
};

async function severeViolations(container: HTMLElement) {
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  return results.violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical",
  );
}

interface RenderOptions {
  initialMaskId?: string | null;
  baseWidth?: number;
  baseHeight?: number;
  gradedBaseAvailable?: boolean;
  analysisReport?: AnalysisReport | null;
  subjectMaskAvailable?: boolean;
  initialCapability?: "outpaint" | "remove" | "local_edit";
  onResultAccepted?: (state: SessionState) => void;
  onResultRejected?: () => void;
  onExit?: () => void;
}

function renderStudio(options: RenderOptions = {}) {
  const {
    initialMaskId = null,
    baseWidth = 800,
    baseHeight = 600,
    gradedBaseAvailable = true,
    analysisReport = null,
    subjectMaskAvailable = false,
    initialCapability,
    onResultAccepted,
    onResultRejected,
    onExit,
  } = options;
  const utils = render(
    <CreativeStudio
      sessionId="sess-123"
      previewImageUrl="/preview/current.png"
      baseWidth={baseWidth}
      baseHeight={baseHeight}
      gradedBaseAvailable={gradedBaseAvailable}
      analysisReport={analysisReport}
      subjectMaskAvailable={subjectMaskAvailable}
      initialCapability={initialCapability}
      originalImageUrl="/images/original.png"
      initialMaskId={initialMaskId}
      onResultAccepted={onResultAccepted}
      onResultRejected={onResultRejected}
      onExit={onExit}
      historySlot={<div data-testid="history-strip">历史版本 1 · 2 · 3</div>}
    />,
  );
  return { ...utils, user: userEvent.setup() };
}

/** Waits for the capabilities round-trip, which gates the submit button. */
async function awaitCapabilities() {
  await waitFor(() => expect(screen.getByText("模拟生成模式")).toBeInTheDocument());
}

function submitButton() {
  return screen.getByRole("button", { name: /^开始 AI / });
}

function payload() {
  return mockCreateTask.mock.calls[0][0];
}

/** A poll that reports the running stage and stays in-flight until `settle()`. */
function pendingPoll(next: GenerativeTaskStatusResponse) {
  let settle: () => void = () => {};
  const gate = new Promise<void>((resolve) => {
    settle = resolve;
  });
  mockPollTask.mockImplementation(async (_taskId, options) => {
    options?.onUpdate?.(MOCK_TASK_PROCESSING);
    await gate;
    return next;
  });
  return { settle };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockGetCapabilities.mockResolvedValue(MOCK_CAPABILITIES);
  mockGetStorage.mockResolvedValue(MOCK_STORAGE);
  mockListStyles.mockResolvedValue({ styles: [] });
  mockListMasks.mockResolvedValue({ items: [mask("mask-001", "brush")] });
  mockCreateTask.mockResolvedValue(MOCK_TASK_CREATED);
  mockPollTask.mockResolvedValue(MOCK_TASK_SUCCEEDED);
  mockAcceptResult.mockResolvedValue(MOCK_SESSION_STATE);
  mockRejectResult.mockResolvedValue({
    ...MOCK_CANDIDATE,
    status: "rejected",
    decidedAt: "2026-11-10T12:00:09Z",
  });
  mockCancelTask.mockResolvedValue({ ...MOCK_TASK_PROCESSING, status: "cancelled", stage: "failed" });
  mockRetryTask.mockResolvedValue(MOCK_TASK_PROCESSING);
});

describe("CreativeStudio four areas", () => {
  it("lays out the tool rail, canvas, parameter panel and history strip", async () => {
    const { container } = renderStudio();
    await awaitCapabilities();

    const rail = container.querySelector<HTMLElement>('[aria-label="创意工作台工具区"]');
    expect(rail).not.toBeNull();
    expect(within(rail as HTMLElement).getByRole("radio", { name: /^AI 画幅扩充/ })).toBeChecked();

    expect(
      screen.getByRole("group", { name: "生成画布，可拖动平移、滚轮缩放" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "AI 画幅扩充", level: 2 })).toBeInTheDocument();

    const section = container.querySelector("#creative-studio") as HTMLElement;
    const history = within(section).getByTestId("history-strip");
    expect(history).toBeInTheDocument();
    expect(section.lastElementChild).toContainElement(history);
  });

  it("leaves the studio through the header button", async () => {
    const onExit = vi.fn();
    const { user } = renderStudio({ onExit });
    await awaitCapabilities();

    await user.click(screen.getByRole("button", { name: "返回参数精修" }));

    expect(onExit).toHaveBeenCalledTimes(1);
  });

  it("has no serious or critical accessibility violations with a candidate ready", async () => {
    const { container, user } = renderStudio();
    await awaitCapabilities();

    await user.click(screen.getByRole("radio", { name: "16:9" }));
    await user.click(submitButton());
    await waitFor(() => expect(screen.getByText("扩图候选结果已就绪")).toBeInTheDocument());
    await user.click(screen.getByRole("radio", { name: "滑动对比" }));

    expect(await severeViolations(container)).toHaveLength(0);
  });
});

describe("CreativeStudio capability switching", () => {
  it("swaps the parameter section and the submitted payload per capability", async () => {
    const { user } = renderStudio();
    await awaitCapabilities();

    await user.click(screen.getByRole("radio", { name: "16:9" }));
    await user.click(submitButton());
    await waitFor(() => expect(mockCreateTask).toHaveBeenCalledTimes(1));
    expect(payload()).toMatchObject({
      sessionId: "sess-123",
      taskType: "outpaint",
      consent: true,
      params: {
        candidates: 1,
        outpaint: { top: 0, bottom: 0, left: 133, right: 134, aspectRatio: "16:9", alignment: "center" },
      },
    });

    await user.click(screen.getByRole("radio", { name: /^AI 智能消除/ }));
    expect(screen.getByRole("heading", { name: "AI 智能消除", level: 2 })).toBeInTheDocument();
    expect(screen.getByText("选择消除区域蒙版")).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "16:9" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "开始 AI 智能消除" }));
    await waitFor(() => expect(mockCreateTask).toHaveBeenCalledTimes(2));
    expect(mockCreateTask.mock.calls[1][0]).toMatchObject({
      taskType: "remove",
      maskId: "mask-001",
      instruction: "remove marked object",
      params: { candidates: 1 },
    });
  });

  it("requires a written instruction before local generation can start", async () => {
    const { user } = renderStudio();
    await awaitCapabilities();

    await user.click(screen.getByRole("radio", { name: /^AI 局部生成/ }));

    expect(screen.getByText("请填写生成指令，例如：把墙面换成风化砖墙")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始 AI 局部生成" })).toBeDisabled();

    await user.type(screen.getByLabelText("生成指令（必填）"), "把墙面换成风化砖墙");
    await user.click(screen.getByRole("button", { name: "开始 AI 局部生成" }));

    await waitFor(() => expect(mockCreateTask).toHaveBeenCalledTimes(1));
    expect(payload()).toMatchObject({
      taskType: "local_edit",
      maskId: "mask-001",
      instruction: "把墙面换成风化砖墙",
    });
  });

  it("marks a capability the provider cannot serve", async () => {
    mockGetCapabilities.mockResolvedValue({
      ...MOCK_CAPABILITIES,
      supportedTaskTypes: ["outpaint"],
    });
    const { user } = renderStudio();
    await awaitCapabilities();

    expect(screen.getByRole("radio", { name: /^AI 智能消除/ })).toBeDisabled();
    expect(screen.getByRole("radio", { name: /^AI 局部生成/ })).toBeDisabled();
    expect(user).toBeDefined();
  });
});

describe("CreativeStudio validation before the request leaves the browser", () => {
  it("blocks an outpaint request that never widens the frame", async () => {
    renderStudio();
    await awaitCapabilities();

    expect(submitButton()).toBeDisabled();
    expect(
      screen.getByText("请选择画幅比例或增加至少一个方向的外扩边距。"),
    ).toBeInTheDocument();
    expect(mockCreateTask).not.toHaveBeenCalled();
  });

  it("blocks a target frame above the provider long edge", async () => {
    mockGetCapabilities.mockResolvedValue({ ...MOCK_CAPABILITIES, maxLongEdge: 2048 });
    const { user } = renderStudio();
    await awaitCapabilities();

    await user.type(screen.getByLabelText("向上扩展 (Top)"), "4000");

    expect(
      await screen.findByText(
        "目标画幅的最长边 4600px 超过当前 Provider 上限 2048px，请减小比例或边距。",
      ),
    ).toBeInTheDocument();
    expect(submitButton()).toBeDisabled();
  });

  it("links the selected mask to both the canvas overlay and the task", async () => {
    mockListMasks.mockResolvedValue({
      items: [mask("mask-001", "brush"), mask("mask-002", "rect")],
    });
    const { container, user } = renderStudio();
    await awaitCapabilities();
    expect(mockListMasks).toHaveBeenCalledWith("sess-123", { limit: 20 }, expect.any(AbortSignal));

    await user.click(screen.getByRole("radio", { name: /^AI 智能消除/ }));
    const canvas = container.querySelector<HTMLElement>(".studio-canvas") as HTMLElement;
    await waitFor(() =>
      expect(
        canvas.querySelector("img[src='/api/v1/generative/masks/mask-001/image']"),
      ).not.toBeNull(),
    );

    const maskGroup = screen.getByRole("radiogroup", { name: "选择消除区域蒙版" });
    await user.click(within(maskGroup).getByRole("radio", { name: /矩形框选/ }));

    await waitFor(() =>
      expect(
        canvas.querySelector("img[src='/api/v1/generative/masks/mask-002/image']"),
      ).not.toBeNull(),
    );

    await user.click(screen.getByRole("button", { name: "开始 AI 智能消除" }));

    await waitFor(() => expect(mockCreateTask).toHaveBeenCalledTimes(1));
    expect(payload()).toMatchObject({ taskType: "remove", maskId: "mask-002" });
  });
});

describe("CreativeStudio task stages", () => {
  it("reports the real backend stage without a percentage", async () => {
    const gate = pendingPoll(MOCK_TASK_SUCCEEDED);
    const { user } = renderStudio();
    await awaitCapabilities();

    await user.click(screen.getByRole("radio", { name: "16:9" }));
    await user.click(submitButton());

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("正在提交至生成引擎...");
    expect(status.textContent).not.toMatch(/%/);
    expect(screen.getByText("底图 · 当前版本")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "正在生成新画幅..." })).toBeDisabled();
    expect(within(status).getByRole("button", { name: "取消任务" })).toBeEnabled();

    gate.settle();
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
  });

  it("cancels a running task from the stage strip", async () => {
    const gate = pendingPoll(MOCK_TASK_SUCCEEDED);
    const { user } = renderStudio();
    await awaitCapabilities();

    await user.click(screen.getByRole("radio", { name: "16:9" }));
    await user.click(submitButton());

    await user.click(await screen.findByRole("button", { name: "取消任务" }));

    expect(mockCancelTask).toHaveBeenCalledWith("task-001");
    gate.settle();
  });
});

describe("CreativeStudio candidate handling", () => {
  it("shows the candidate on the canvas and pushes the version line on accept", async () => {
    const onResultAccepted = vi.fn();
    const { container, user } = renderStudio({ onResultAccepted });
    await awaitCapabilities();

    await user.click(screen.getByRole("radio", { name: "16:9" }));
    await user.click(submitButton());
    await waitFor(() => expect(screen.getByText("扩图候选结果已就绪")).toBeInTheDocument());

    expect(screen.getByRole("img", { name: "AI 生成结果" })).toHaveAttribute(
      "src",
      "/api/v1/generative/results/res-001/image",
    );
    expect(screen.getByRole("radio", { name: "并排对比" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "采纳新画幅并推进版本" }));

    await waitFor(() => expect(onResultAccepted).toHaveBeenCalledWith(MOCK_SESSION_STATE));
    expect(screen.queryByText("扩图候选结果已就绪")).not.toBeInTheDocument();
    expect(
      container.querySelector('[aria-label="AI 生成结果"]'),
    ).not.toBeInTheDocument();
  });

  it("drops the candidate without touching the revision chain", async () => {
    const onResultRejected = vi.fn();
    const { user } = renderStudio({ onResultRejected });
    await awaitCapabilities();

    await user.click(screen.getByRole("radio", { name: "16:9" }));
    await user.click(submitButton());
    await waitFor(() => expect(screen.getByText("扩图候选结果已就绪")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "放弃" }));

    await waitFor(() => expect(onResultRejected).toHaveBeenCalledTimes(1));
    expect(mockAcceptResult).not.toHaveBeenCalled();
  });

  it("hides the candidate when the result preview is turned off", async () => {
    const { user } = renderStudio();
    await awaitCapabilities();

    await user.click(screen.getByRole("radio", { name: "16:9" }));
    await user.click(submitButton());
    await waitFor(() => expect(screen.getByText("AI 结果")).toBeInTheDocument());

    await user.click(
      screen.getByRole("button", { name: "结果预览：显示 AI 候选" }),
    );

    expect(screen.queryByRole("img", { name: "AI 生成结果" })).not.toBeInTheDocument();
    expect(screen.getByText("底图 · 当前版本")).toBeInTheDocument();
  });
});

describe("CreativeStudio error guidance", () => {
  it("categorises a provider failure and offers the next step", async () => {
    mockCreateTask.mockRejectedValue(
      new ApiClientError("generative_provider_rate_limited", "429", 429, {}, "req-abcdef12"),
    );
    const { user } = renderStudio();
    await awaitCapabilities();

    await user.click(screen.getByRole("radio", { name: "16:9" }));
    await user.click(submitButton());

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Provider 错误");
    expect(alert).toHaveTextContent("下一步：稍等片刻再提交，或在 Provider 侧提高调用频率上限。");
    expect(alert).toHaveTextContent("generative_provider_rate_limited");
  });

  it("categorises a lost connection as a network problem", async () => {
    mockCreateTask.mockRejectedValue(new ApiClientError("network_error", "无法连接 API 服务。", 0));
    const { user } = renderStudio();
    await awaitCapabilities();

    await user.click(screen.getByRole("radio", { name: "16:9" }));
    await user.click(submitButton());

    expect(await screen.findByRole("alert")).toHaveTextContent("网络错误");
  });

  it("surfaces the stage the backend failed in and offers a retry", async () => {
    mockPollTask.mockResolvedValue(MOCK_TASK_FAILED);
    const { user } = renderStudio();
    await awaitCapabilities();

    await user.click(screen.getByRole("radio", { name: "16:9" }));
    await user.click(submitButton());

    expect(await screen.findByRole("alert")).toHaveTextContent("生成失败");
    await user.click(screen.getByRole("button", { name: "重试 AI 画幅扩充" }));
    await waitFor(() => expect(mockPollTask).toHaveBeenCalledTimes(2));
  });

  it("reports a mask the backend no longer has", async () => {
    mockCreateTask.mockRejectedValue(
      new ApiClientError("generative_mask_missing", "gone", 404, {}, null),
    );
    const { user } = renderStudio();
    await awaitCapabilities();

    await user.click(screen.getByRole("radio", { name: /^AI 智能消除/ }));
    await user.click(screen.getByRole("button", { name: "开始 AI 智能消除" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("蒙版错误");
    expect(alert).toHaveTextContent("下一步：重新绘制或重新选择蒙版");
  });
});

describe("CreativeStudio graded input base", () => {
  function baseModeGroup() {
    return screen.getByRole("radiogroup", { name: "输入基准" });
  }

  it("keeps the untouched base by default", async () => {
    const { user } = renderStudio();
    await awaitCapabilities();

    expect(within(baseModeGroup()).getByRole("radio", { name: "当前基准" })).toBeChecked();
    await user.click(screen.getByRole("radio", { name: "16:9" }));
    await user.click(submitButton());

    await waitFor(() => expect(mockCreateTask).toHaveBeenCalledTimes(1));
    expect(payload()).toMatchObject({ taskType: "outpaint", baseMode: "base" });
  });

  it("sends baseMode=graded and promises byte-level write-back of the flattened pixels", async () => {
    const { user } = renderStudio();
    await awaitCapabilities();

    await user.click(within(baseModeGroup()).getByRole("radio", { name: "已调色版本" }));
    expect(screen.getByText(/保护区按压平后的已调色像素逐字节写回/)).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: /^AI 智能消除/ }));
    await user.click(screen.getByRole("button", { name: "开始 AI 智能消除" }));

    await waitFor(() => expect(mockCreateTask).toHaveBeenCalledTimes(1));
    expect(payload()).toMatchObject({ taskType: "remove", baseMode: "graded" });
  });

  it("disables the graded base when the committed recipe carries crop or rotation", async () => {
    const { user } = renderStudio({ gradedBaseAvailable: false });
    await awaitCapabilities();

    const graded = within(baseModeGroup()).getByRole("radio", { name: "已调色版本" });
    expect(graded).toBeDisabled();
    expect(graded).not.toBeChecked();
    expect(within(baseModeGroup()).getByRole("radio", { name: "当前基准" })).toBeChecked();
    expect(screen.getByText(/当前版本含裁切或旋转，已调色基准暂不可用/)).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "16:9" }));
    await user.click(submitButton());

    await waitFor(() => expect(mockCreateTask).toHaveBeenCalledTimes(1));
    expect(payload()).toMatchObject({ baseMode: "base" });
  });
});

describe("CreativeStudio analysis suggestions", () => {
  it("fills the capability and instruction without submitting", async () => {
    const report = analysisReport({
      issues: [
        {
          id: "detail",
          type: "low_detail",
          severity: "high",
          confidence: 0.9,
          evidence: "主体区域纹理不足。",
          suggestion: null,
          regionIds: ["region_001"],
        },
      ],
    });
    const { user } = renderStudio({ analysisReport: report });
    await awaitCapabilities();

    await user.click(screen.getByRole("button", { name: "填入局部生成指令" }));

    expect(screen.getByRole("radio", { name: /^AI 局部生成/ })).toBeChecked();
    expect(screen.getByLabelText("生成指令（必填）")).toHaveValue(
      "在选定区域补回真实纹理细节，保持原有光线与色彩",
    );
    expect(screen.getByText("关联主体：人物，可据此绘制矩形蒙版。")).toBeInTheDocument();
    expect(mockCreateTask).not.toHaveBeenCalled();
  });

  it("fills an outpaint instruction for a composition defect", async () => {
    const report = analysisReport({
      issues: [
        {
          id: "space",
          type: "negative_space_issue",
          severity: "medium",
          confidence: 0.7,
          evidence: "留白偏少。",
          suggestion: null,
          regionIds: [],
        },
      ],
    });
    const { user } = renderStudio({ analysisReport: report });
    await awaitCapabilities();

    await user.click(screen.getByRole("button", { name: "填入扩图指令" }));

    expect(screen.getByRole("radio", { name: /^AI 画幅扩充/ })).toBeChecked();
    expect(screen.getByLabelText("扩图指示提示词（可选）")).toHaveValue(
      "向外扩展画面补足留白，保持主体位置、透视与原有光线一致",
    );
    expect(mockCreateTask).not.toHaveBeenCalled();
  });

  it("keeps exposure advice in 参数精修 instead of offering a generation action", async () => {
    renderStudio({ analysisReport: analysisReport() });
    await awaitCapabilities();

    expect(screen.getByText("建议在参数精修中处理")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^填入/ })).toBeNull();
    expect(screen.getByText("整体欠曝")).toBeInTheDocument();
    expect(
      screen.getByText(/提高整体曝光或针对暗部做适度提亮。/),
    ).toBeInTheDocument();
    expect(mockCreateTask).not.toHaveBeenCalled();
  });

  it("hides the block when no analysis report is available", async () => {
    renderStudio();
    await awaitCapabilities();

    expect(screen.queryByRole("heading", { name: "分析建议" })).toBeNull();
  });
});

describe("CreativeStudio personal style presets", () => {
  const STYLE_NAME = "我的风格（Visual DNA）";

  async function openLocalEdit() {
    const utils = renderStudio();
    await awaitCapabilities();
    await utils.user.click(screen.getByRole("radio", { name: /^AI 局部生成/ }));
    return utils;
  }

  it("fills the style instruction and sends it only after an explicit submit", async () => {
    mockListStyles.mockResolvedValue({
      styles: [personalStyleItem({ status: "published" })],
    });
    const { user } = await openLocalEdit();

    await user.selectOptions(
      await screen.findByRole("combobox", { name: STYLE_NAME }),
      PERSONAL_STYLE_ID,
    );

    const instruction = screen.getByLabelText("生成指令（必填）");
    expect(instruction).toHaveValue(buildStyleInstruction(personalStyleItem({ status: "published" })));
    expect(screen.getByText(/风格指令会随画面一起发送到该 Provider/)).toBeInTheDocument();
    expect(mockCreateTask).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "开始 AI 局部生成" }));

    await waitFor(() => expect(mockCreateTask).toHaveBeenCalledTimes(1));
    expect(payload()).toMatchObject({
      taskType: "local_edit",
      instruction: buildStyleInstruction(personalStyleItem({ status: "published" })),
    });
  });

  it("offers only published and enabled styles", async () => {
    mockListStyles.mockResolvedValue({
      styles: [
        personalStyleItem({ id: "draft", name: "草稿风格", status: "draft" }),
        personalStyleItem({ id: "off", name: "停用风格", status: "published", enabled: false }),
        personalStyleItem({ status: "published" }),
      ],
    });
    await openLocalEdit();

    const select = await screen.findByRole("combobox", { name: STYLE_NAME });
    expect(within(select).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "不使用风格",
      "克制的城市叙事",
    ]);
  });

  it("keeps the edited instruction when the preset is cleared", async () => {
    mockListStyles.mockResolvedValue({
      styles: [personalStyleItem({ status: "published" })],
    });
    const { user } = await openLocalEdit();

    const select = await screen.findByRole("combobox", { name: STYLE_NAME });
    await user.selectOptions(select, PERSONAL_STYLE_ID);
    await user.clear(screen.getByLabelText("生成指令（必填）"));
    await user.type(screen.getByLabelText("生成指令（必填）"), "把墙面换成风化砖墙");
    await user.selectOptions(select, "");

    expect(screen.getByLabelText("生成指令（必填）")).toHaveValue("把墙面换成风化砖墙");
    expect(screen.queryByText(/风格指令会随画面一起发送到该 Provider/)).toBeNull();
  });

  it("explains when Visual DNA has no usable style", async () => {
    await openLocalEdit();

    expect(
      await screen.findByText(/Visual DNA 中暂无已发布并启用的个人风格/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: STYLE_NAME })).toBeNull();
  });

  it("keeps the preset out of the other capabilities", async () => {
    mockListStyles.mockResolvedValue({
      styles: [personalStyleItem({ status: "published" })],
    });
    renderStudio();
    await awaitCapabilities();

    expect(screen.queryByRole("combobox", { name: STYLE_NAME })).toBeNull();
  });
});

describe("CreativeStudio subject masks", () => {
  const SUBJECT_REPORT = analysisReport({
    issues: [
      {
        id: "detail",
        type: "low_detail",
        severity: "high",
        confidence: 0.9,
        evidence: "主体区域纹理不足。",
        suggestion: null,
        regionIds: ["region_001"],
      },
    ],
  });

  it("creates a rect mask from the analysis subject and selects it", async () => {
    mockCreateMask.mockResolvedValue(mask("subject-mask-001", "rect"));
    const { user } = renderStudio({
      analysisReport: SUBJECT_REPORT,
      subjectMaskAvailable: true,
    });
    await awaitCapabilities();

    await user.click(screen.getByRole("button", { name: "填入局部生成指令" }));
    await user.click(screen.getByRole("button", { name: "用主体区域建蒙版" }));

    await waitFor(() => expect(mockCreateMask).toHaveBeenCalledTimes(1));
    expect(mockCreateMask.mock.calls[0][0]).toEqual({
      sessionId: "sess-123",
      kind: "rect",
      definition: {
        region: { x: 0.2, y: 0.1, width: 0.4, height: 0.7 },
        expand: 0,
      },
      feather: 0,
      inverted: false,
    });
    expect(await screen.findByText("当前已选蒙版: subject-...")).toBeInTheDocument();
    expect(mockCreateTask).not.toHaveBeenCalled();
  });

  it("offers no subject mask when the base is a generated asset", async () => {
    renderStudio({ analysisReport: SUBJECT_REPORT });
    await awaitCapabilities();

    expect(screen.getByText("关联主体：人物，可据此绘制矩形蒙版。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "用主体区域建蒙版" })).toBeNull();
  });

  it("reports the backend reason when the subject mask is rejected", async () => {
    mockCreateMask.mockRejectedValue(
      new ApiClientError("generative_mask_invalid", "蒙版区域过小。", 422),
    );
    const { user } = renderStudio({
      analysisReport: SUBJECT_REPORT,
      subjectMaskAvailable: true,
    });
    await awaitCapabilities();

    await user.click(screen.getByRole("button", { name: "用主体区域建蒙版" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("蒙版区域过小。");
  });

  it("opens on the capability the caller presets", async () => {
    renderStudio({ initialCapability: "remove", initialMaskId: "mask-001" });
    await awaitCapabilities();

    expect(screen.getByRole("radio", { name: /^AI 智能消除/ })).toBeChecked();
    expect(screen.getByRole("button", { name: "开始 AI 智能消除" })).toBeEnabled();
  });
});

describe("CreativeStudio storage budget meter", () => {
  it("displays the storage usage meter", async () => {
    renderStudio();
    await awaitCapabilities();

    expect(await screen.findByTestId("generative-storage-meter")).toBeInTheDocument();
    expect(screen.getByText("本机 AI 存储预算")).toBeInTheDocument();
  });

  it("disables submit and shows error guidance when storage is full", async () => {
    mockGetStorage.mockResolvedValue({
      usedBytes: 2048 * 1024 * 1024,
      limitBytes: 2048 * 1024 * 1024,
      assetBytes: 2000 * 1024 * 1024,
      resultBytes: 48 * 1024 * 1024,
      maskBytes: 0,
      retentionDays: 7,
    });
    const { user } = renderStudio();
    await awaitCapabilities();

    await user.click(screen.getByRole("radio", { name: "16:9" }));
    expect(await screen.findByText(/存储预算已耗尽/)).toBeInTheDocument();
    expect(submitButton()).toBeDisabled();
    expect(screen.getByText(/生成式存储已达上限/)).toBeInTheDocument();
  });
});
