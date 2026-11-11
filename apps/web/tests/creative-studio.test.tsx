import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreativeStudio } from "@/features/generative/studio/creative-studio";
import { ApiClientError } from "@/lib/api/client";
import * as generativeApi from "@/lib/api/generative";
import type {
  GenerativeCapabilitiesResponse,
  GenerativeMaskView,
  GenerativeResultView,
  GenerativeTaskCreated,
  GenerativeTaskStatusResponse,
} from "@/types/generative";
import type { SessionState } from "@/types/session";

vi.mock("@/lib/api/generative", () => ({
  getGenerativeCapabilities: vi.fn(),
  listGenerativeMasks: vi.fn(),
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
const mockListMasks = vi.mocked(generativeApi.listGenerativeMasks);
const mockCreateTask = vi.mocked(generativeApi.createGenerativeTask);
const mockPollTask = vi.mocked(generativeApi.pollGenerativeTask);
const mockAcceptResult = vi.mocked(generativeApi.acceptGenerativeResult);
const mockRejectResult = vi.mocked(generativeApi.rejectGenerativeResult);
const mockCancelTask = vi.mocked(generativeApi.cancelGenerativeTask);
const mockRetryTask = vi.mocked(generativeApi.retryGenerativeTask);

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
  onResultAccepted?: (state: SessionState) => void;
  onResultRejected?: () => void;
  onExit?: () => void;
}

function renderStudio(options: RenderOptions = {}) {
  const { initialMaskId = null, onResultAccepted, onResultRejected, onExit } = options;
  const utils = render(
    <CreativeStudio
      sessionId="sess-123"
      previewImageUrl="/preview/current.png"
      previewWidth={800}
      previewHeight={600}
      originalImageUrl="/images/original.png"
      imageWidth={800}
      imageHeight={600}
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
