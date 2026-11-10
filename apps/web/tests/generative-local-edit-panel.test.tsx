import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GenerativeLocalEditPanel } from "@/features/generative/components/generative-local-edit-panel";
import * as generativeApi from "@/lib/api/generative";
import type {
  GenerativeCapabilitiesResponse,
  GenerativeMaskView,
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
const mockRetryTask = vi.mocked(generativeApi.retryGenerativeTask);
const mockAcceptResult = vi.mocked(generativeApi.acceptGenerativeResult);
const mockRejectResult = vi.mocked(generativeApi.rejectGenerativeResult);

const MOCK_CAPABILITIES: GenerativeCapabilitiesResponse = {
  provider: "mock",
  model: "generative-mock-1",
  isMock: true,
  supportedTaskTypes: ["local_edit", "outpaint", "remove"],
  supportsMask: true,
  supportsMultipleOutputs: false,
  maxOutputPixels: 24_000_000,
  maxLongEdge: 8192,
  allowedOutputFormats: ["png"],
  declaredRetention: "Mock provider",
  notes: [],
};

const MOCK_MASK_1: GenerativeMaskView = {
  maskId: "mask-001",
  imageId: "img-001",
  baseGeneratedAssetId: null,
  kind: "rect",
  source: "user",
  coordinateSpace: "base-normalized",
  width: 800,
  height: 600,
  imageUrl: "/api/v1/generative/masks/mask-001/image",
  sha256: "0".repeat(64),
  feather: 0,
  inverted: false,
  quality: {
    coverage: 0.18,
    componentCount: 1,
    touchesBorder: false,
    warnings: [],
  },
  definition: {
    strokes: [],
    expand: 0,
  },
  createdAt: "2026-11-10T12:00:00Z",
};

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

const MOCK_TASK_SUCCEEDED: GenerativeTaskStatusResponse = {
  taskId: "task-001",
  taskType: "local_edit",
  status: "succeeded",
  stage: "completed",
  instruction: "把墙面换成风化砖墙",
  isMock: true,
  provider: "mock",
  model: "mock-1",
  attempts: 1,
  maxAttempts: 2,
  cancelRequested: false,
  createdAt: "2026-11-10T12:00:00Z",
  updatedAt: "2026-11-10T12:00:05Z",
  expiresAt: "2026-11-11T00:00:00Z",
  results: [
    {
      resultId: "res-001",
      resultIndex: 0,
      status: "candidate",
      width: 800,
      height: 600,
      imageUrl: "/api/v1/generative/results/res-001/image",
      warnings: ["mock_output", "protected_region_restored"],
      createdAt: "2026-11-10T12:00:05Z",
    },
  ],
};

const MOCK_TASK_FAILED: GenerativeTaskStatusResponse = {
  ...MOCK_TASK_SUCCEEDED,
  status: "failed",
  stage: "failed",
  error: {
    code: "generative_instruction_required",
    message: "局部生成需要提供生成指令。",
  },
  results: [],
};

const MOCK_SESSION_STATE: SessionState = {
  sessionId: "sess-123",
  imageId: "img-001",
  activeRevisionId: "rev-2",
  headRevisionId: "rev-2",
  canUndo: true,
  canRedo: false,
  revision: {
    id: "rev-2",
    revisionNo: 2,
    parentId: "rev-1",
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

const SUBMIT_BUTTON = "开始 AI 局部生成";

async function severeViolations(container: HTMLElement) {
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  return results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

describe("GenerativeLocalEditPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetCapabilities.mockResolvedValue(MOCK_CAPABILITIES);
    mockListMasks.mockResolvedValue({ items: [MOCK_MASK_1] });
  });

  it("renders the mask picker, instruction field and protection notice", async () => {
    render(<GenerativeLocalEditPanel sessionId="sess-123" initialMaskId="mask-001" />);

    expect(
      screen.getByRole("heading", { name: /AI 局部生成式修改/ }),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("模拟生成模式")).toBeInTheDocument();
      expect(screen.getByText("矩形框选")).toBeInTheDocument();
    });
    expect(screen.getByRole("radiogroup", { name: /选择编辑区域蒙版/ })).toBeInTheDocument();
    expect(screen.getByLabelText(/生成指令（必填）/)).toBeInTheDocument();
    expect(screen.getByText(/蒙版需保留至少 5%/)).toBeInTheDocument();
  });

  it("keeps the task disabled until an instruction is written", async () => {
    const user = userEvent.setup();
    render(<GenerativeLocalEditPanel sessionId="sess-123" initialMaskId="mask-001" />);

    expect(screen.getByRole("button", { name: SUBMIT_BUTTON })).toBeDisabled();

    await user.type(screen.getByLabelText(/生成指令（必填）/), "把墙面换成风化砖墙");

    expect(screen.getByRole("button", { name: SUBMIT_BUTTON })).toBeEnabled();
    expect(mockCreateTask).not.toHaveBeenCalled();
  });

  it("disables the task when the session has no mask", async () => {
    const user = userEvent.setup();
    mockListMasks.mockResolvedValue({ items: [] });
    render(<GenerativeLocalEditPanel sessionId="sess-123" />);

    await screen.findByText(/当前会话暂无蒙版/);
    await user.type(screen.getByLabelText(/生成指令（必填）/), "adds fog");

    expect(screen.getByRole("button", { name: SUBMIT_BUTTON })).toBeDisabled();
  });

  it("submits a local edit task and accepts the candidate", async () => {
    const user = userEvent.setup();
    mockCreateTask.mockResolvedValue(MOCK_TASK_CREATED);
    mockPollTask.mockResolvedValue(MOCK_TASK_SUCCEEDED);
    mockAcceptResult.mockResolvedValue(MOCK_SESSION_STATE);

    const onAccepted = vi.fn();
    render(
      <GenerativeLocalEditPanel
        sessionId="sess-123"
        initialMaskId="mask-001"
        onResultAccepted={onAccepted}
      />,
    );

    await user.type(screen.getByLabelText(/生成指令（必填）/), "  把墙面换成风化砖墙  ");
    await user.click(screen.getByRole("button", { name: SUBMIT_BUTTON }));

    await waitFor(() => {
      expect(mockCreateTask).toHaveBeenCalledWith(
        expect.objectContaining({
          sessionId: "sess-123",
          taskType: "local_edit",
          instruction: "把墙面换成风化砖墙",
          maskId: "mask-001",
          consent: true,
        }),
        undefined,
        expect.any(AbortSignal),
      );
    });

    await waitFor(() => {
      expect(screen.getByText("局部生成候选结果已就绪")).toBeInTheDocument();
      expect(screen.getByText("未选区域 100% 原始字节恢复")).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "采纳局部生成结果并推进版本" }),
      ).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "采纳局部生成结果并推进版本" }));
    await waitFor(() => {
      expect(mockAcceptResult).toHaveBeenCalledWith("res-001");
      expect(onAccepted).toHaveBeenCalledWith(MOCK_SESSION_STATE);
    });
    expect(screen.queryByText("局部生成候选结果已就绪")).not.toBeInTheDocument();
  });

  it("rejects the candidate and keeps the current revision", async () => {
    const user = userEvent.setup();
    mockCreateTask.mockResolvedValue(MOCK_TASK_CREATED);
    mockPollTask.mockResolvedValue(MOCK_TASK_SUCCEEDED);
    mockRejectResult.mockResolvedValue(MOCK_TASK_SUCCEEDED.results![0]);

    const onRejected = vi.fn();
    render(
      <GenerativeLocalEditPanel
        sessionId="sess-123"
        initialMaskId="mask-001"
        onResultRejected={onRejected}
      />,
    );

    await user.type(screen.getByLabelText(/生成指令（必填）/), "replace with water");
    await user.click(screen.getByRole("button", { name: SUBMIT_BUTTON }));

    await screen.findByText("局部生成候选结果已就绪");
    await user.click(screen.getByRole("button", { name: "放弃" }));

    await waitFor(() => {
      expect(mockRejectResult).toHaveBeenCalledWith("res-001");
      expect(onRejected).toHaveBeenCalled();
    });
    expect(screen.queryByText("局部生成候选结果已就绪")).not.toBeInTheDocument();
  });

  it("shows the task error and recovers through retry", async () => {
    const user = userEvent.setup();
    mockCreateTask.mockResolvedValue(MOCK_TASK_CREATED);
    mockPollTask
      .mockResolvedValueOnce(MOCK_TASK_FAILED)
      .mockResolvedValueOnce(MOCK_TASK_SUCCEEDED);
    mockRetryTask.mockResolvedValue({
      ...MOCK_TASK_SUCCEEDED,
      status: "queued",
      stage: "queued",
      results: [],
    });

    render(<GenerativeLocalEditPanel sessionId="sess-123" initialMaskId="mask-001" />);

    await user.type(screen.getByLabelText(/生成指令（必填）/), "make it dusk");
    await user.click(screen.getByRole("button", { name: SUBMIT_BUTTON }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
      expect(screen.getByText(/局部生成需要提供生成指令/)).toBeInTheDocument();
    });

    const retryButton = screen.getByRole("button", { name: "重试局部生成任务" });
    await user.click(retryButton);

    await waitFor(() => {
      expect(mockRetryTask).toHaveBeenCalledWith("task-001");
    });
    await screen.findByText("局部生成候选结果已就绪");
  });

  it("surfaces an API failure as an alert", async () => {
    const user = userEvent.setup();
    mockCreateTask.mockRejectedValue(new Error("网络连接失败，请稍后重试"));

    render(<GenerativeLocalEditPanel sessionId="sess-123" initialMaskId="mask-001" />);

    await user.type(screen.getByLabelText(/生成指令（必填）/), "make it dusk");
    await user.click(screen.getByRole("button", { name: SUBMIT_BUTTON }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
      expect(screen.getByText(/网络连接失败/)).toBeInTheDocument();
    });
  });

  it("satisfies axe accessibility standards", async () => {
    const { container } = render(
      <GenerativeLocalEditPanel sessionId="sess-123" initialMaskId="mask-001" />,
    );

    await waitFor(() => {
      expect(screen.getByText("矩形框选")).toBeInTheDocument();
    });

    expect(await severeViolations(container)).toEqual([]);
  });
});
