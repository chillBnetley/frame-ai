import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GenerativeRemovalPanel } from "@/features/generative/components/generative-removal-panel";
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
  kind: "brush",
  source: "user",
  coordinateSpace: "base-normalized",
  width: 800,
  height: 600,
  imageUrl: "/api/v1/generative/masks/mask-001/image",
  sha256: "0".repeat(64),
  feather: 2,
  inverted: false,
  quality: {
    coverage: 0.05,
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
  taskType: "remove",
  status: "succeeded",
  stage: "completed",
  instruction: "remove marked object",
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

async function severeViolations(container: HTMLElement) {
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  return results.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
}

describe("GenerativeRemovalPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetCapabilities.mockResolvedValue(MOCK_CAPABILITIES);
    mockListMasks.mockResolvedValue({ items: [MOCK_MASK_1] });
  });

  it("renders with initial state, capabilities, and listed masks", async () => {
    render(<GenerativeRemovalPanel sessionId="sess-123" />);

    expect(screen.getByRole("heading", { name: /AI 智能消除/ })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("模拟生成模式")).toBeInTheDocument();
      expect(screen.getByText("画笔蒙版")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "开始 AI 智能消除" })).toBeEnabled();
  });

  it("disables start button when no mask is selected", async () => {
    mockListMasks.mockResolvedValue({ items: [] });
    render(<GenerativeRemovalPanel sessionId="sess-123" />);

    await waitFor(() => {
      expect(screen.getByText(/当前会话暂无蒙版/)).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "开始 AI 智能消除" })).toBeDisabled();
  });

  it("submits removal task and handles acceptance", async () => {
    const user = userEvent.setup();
    mockCreateTask.mockResolvedValue(MOCK_TASK_CREATED);
    mockPollTask.mockResolvedValue(MOCK_TASK_SUCCEEDED);
    mockAcceptResult.mockResolvedValue(MOCK_SESSION_STATE);

    const onAccepted = vi.fn();
    render(
      <GenerativeRemovalPanel
        sessionId="sess-123"
        initialMaskId="mask-001"
        onResultAccepted={onAccepted}
      />,
    );

    const promptInput = screen.getByLabelText(/消除指示提示词/);
    await user.type(promptInput, "消除背景杂乱电线");

    const submitBtn = screen.getByRole("button", { name: "开始 AI 智能消除" });
    await user.click(submitBtn);

    await waitFor(() => {
      expect(mockCreateTask).toHaveBeenCalledWith(
        expect.objectContaining({
          sessionId: "sess-123",
          taskType: "remove",
          instruction: "消除背景杂乱电线",
          maskId: "mask-001",
        }),
        undefined,
        expect.any(AbortSignal),
      );
    });

    await waitFor(() => {
      expect(screen.getByText("消除候选结果已就绪")).toBeInTheDocument();
      expect(screen.getByText("保护区 100% 原始字节恢复")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "采纳消除结果并推进版本" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "放弃" })).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "采纳消除结果并推进版本" }));
    await waitFor(() => {
      expect(mockAcceptResult).toHaveBeenCalledWith("res-001");
      expect(onAccepted).toHaveBeenCalledWith(MOCK_SESSION_STATE);
    });
  });

  it("handles rejection of candidate result", async () => {
    const user = userEvent.setup();
    mockCreateTask.mockResolvedValue(MOCK_TASK_CREATED);
    mockPollTask.mockResolvedValue(MOCK_TASK_SUCCEEDED);
    mockRejectResult.mockResolvedValue(MOCK_TASK_SUCCEEDED.results![0]);

    const onRejected = vi.fn();
    render(
      <GenerativeRemovalPanel
        sessionId="sess-123"
        initialMaskId="mask-001"
        onResultRejected={onRejected}
      />,
    );

    await user.click(screen.getByRole("button", { name: "开始 AI 智能消除" }));

    await screen.findByText("消除候选结果已就绪");
    await user.click(screen.getByRole("button", { name: "放弃" }));

    await waitFor(() => {
      expect(mockRejectResult).toHaveBeenCalledWith("res-001");
      expect(onRejected).toHaveBeenCalled();
    });
  });

  it("displays error message on submission failure", async () => {
    const user = userEvent.setup();
    mockCreateTask.mockRejectedValue(new Error("网络连接失败，请稍后重试"));

    render(
      <GenerativeRemovalPanel
        sessionId="sess-123"
        initialMaskId="mask-001"
      />,
    );

    await user.click(screen.getByRole("button", { name: "开始 AI 智能消除" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
      expect(screen.getByText(/网络连接失败/)).toBeInTheDocument();
    });
  });

  it("satisfies axe accessibility standards", async () => {
    const { container } = render(
      <GenerativeRemovalPanel sessionId="sess-123" initialMaskId="mask-001" />,
    );

    await waitFor(() => {
      expect(screen.getByText("画笔蒙版")).toBeInTheDocument();
    });

    const violations = await severeViolations(container);
    expect(violations).toEqual([]);
  });
});
