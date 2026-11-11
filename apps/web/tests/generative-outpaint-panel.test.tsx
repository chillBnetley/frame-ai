import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GenerativeOutpaintPanel } from "@/features/generative/components/generative-outpaint-panel";
import * as generativeApi from "@/lib/api/generative";
import type {
  GenerativeCapabilitiesResponse,
  GenerativeTaskCreated,
  GenerativeTaskStatusResponse,
} from "@/types/generative";
import type { SessionState } from "@/types/session";

vi.mock("@/lib/api/generative", () => ({
  getGenerativeCapabilities: vi.fn(),
  createGenerativeTask: vi.fn(),
  getGenerativeTask: vi.fn(),
  cancelGenerativeTask: vi.fn(),
  retryGenerativeTask: vi.fn(),
  pollGenerativeTask: vi.fn(),
  acceptGenerativeResult: vi.fn(),
  rejectGenerativeResult: vi.fn(),
  generativeResultImageUrl: vi.fn((id: string) => `/api/v1/generative/results/${id}/image`),
}));

const mockGetCapabilities = vi.mocked(generativeApi.getGenerativeCapabilities);
const mockCreateTask = vi.mocked(generativeApi.createGenerativeTask);
const mockPollTask = vi.mocked(generativeApi.pollGenerativeTask);
const mockAcceptResult = vi.mocked(generativeApi.acceptGenerativeResult);
const mockRejectResult = vi.mocked(generativeApi.rejectGenerativeResult);

const MOCK_CAPABILITIES: GenerativeCapabilitiesResponse = {
  provider: "mock",
  model: "generative-mock-1",
  isMock: true,
  supportedTaskTypes: ["local_edit", "outpaint"],
  supportsMask: true,
  supportsMultipleOutputs: false,
  maxOutputPixels: 24_000_000,
  maxLongEdge: 8192,
  allowedOutputFormats: ["png"],
  declaredRetention: "Mock provider",
  minEdge: 0,
  notes: [],
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
  taskType: "outpaint",
  baseMode: "base",
  status: "succeeded",
  stage: "completed",
  instruction: "expand horizon",
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
      width: 1920,
      height: 1080,
      imageUrl: "/api/v1/generative/results/res-001/image",
      warnings: ["mock_output", "outpaint_region_extended"],
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

describe("GenerativeOutpaintPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetCapabilities.mockResolvedValue(MOCK_CAPABILITIES);
  });

  it("renders with default state and mock badge", async () => {
    render(<GenerativeOutpaintPanel sessionId="sess-123" baseWidth={1000} baseHeight={1000} />);

    expect(screen.getByRole("heading", { name: /AI 画幅扩充/ })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("模拟生成模式")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "开始 AI 画幅扩充" })).toBeDisabled();
  });

  it("enables generation when selecting a ratio preset", async () => {
    const user = userEvent.setup();
    render(<GenerativeOutpaintPanel sessionId="sess-123" baseWidth={1000} baseHeight={1000} />);

    const ratio169 = screen.getByRole("radio", { name: "16:9" });
    await user.click(ratio169);

    expect(ratio169).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText("画面对齐定位")).toBeInTheDocument();
    expect(screen.getByText(/1778 × 1000/)).toBeInTheDocument();

    const submitBtn = screen.getByRole("button", { name: "开始 AI 画幅扩充" });
    expect(submitBtn).toBeEnabled();
  });

  it("enables generation when entering custom pixel margins", async () => {
    const user = userEvent.setup();
    render(<GenerativeOutpaintPanel sessionId="sess-123" baseWidth={1000} baseHeight={1000} />);

    const topInput = screen.getByLabelText(/向上扩展/);
    await user.clear(topInput);
    await user.type(topInput, "150");

    expect(screen.getByText(/1000 × 1150/)).toBeInTheDocument();
    const submitBtn = screen.getByRole("button", { name: "开始 AI 画幅扩充" });
    expect(submitBtn).toBeEnabled();
  });

  it("submits task and renders completed result with accept/reject buttons", async () => {
    const user = userEvent.setup();
    mockCreateTask.mockResolvedValue(MOCK_TASK_CREATED);
    mockPollTask.mockResolvedValue(MOCK_TASK_SUCCEEDED);

    const onAccepted = vi.fn();
    const onRejected = vi.fn();

    render(
      <GenerativeOutpaintPanel
        sessionId="sess-123"
        baseWidth={800}
        baseHeight={600}
        onResultAccepted={onAccepted}
        onResultRejected={onRejected}
      />,
    );

    await user.click(screen.getByRole("radio", { name: "16:9" }));

    const submitBtn = screen.getByRole("button", { name: "开始 AI 画幅扩充" });
    await user.click(submitBtn);

    await waitFor(() => {
      expect(mockCreateTask).toHaveBeenCalledWith(
        expect.objectContaining({
          sessionId: "sess-123",
          taskType: "outpaint",
        }),
        undefined,
        expect.any(AbortSignal),
      );
    });

    await waitFor(() => {
      expect(screen.getByText("扩图候选结果已就绪")).toBeInTheDocument();
      expect(screen.getByText("1920 × 1080")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "采纳新画幅并推进版本" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "放弃" })).toBeInTheDocument();
    });

    // Test accept
    mockAcceptResult.mockResolvedValue(MOCK_SESSION_STATE);
    await user.click(screen.getByRole("button", { name: "采纳新画幅并推进版本" }));

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
      <GenerativeOutpaintPanel
        sessionId="sess-123"
        baseWidth={800}
        baseHeight={600}
        onResultRejected={onRejected}
      />,
    );

    await user.click(screen.getByRole("radio", { name: "16:9" }));
    await user.click(screen.getByRole("button", { name: "开始 AI 画幅扩充" }));

    await screen.findByText("扩图候选结果已就绪");
    await user.click(screen.getByRole("button", { name: "放弃" }));

    await waitFor(() => {
      expect(mockRejectResult).toHaveBeenCalledWith("res-001");
      expect(onRejected).toHaveBeenCalled();
      expect(screen.queryByText("扩图候选结果已就绪")).not.toBeInTheDocument();
    });
  });

  it("displays error message on submission failure", async () => {
    const user = userEvent.setup();
    mockCreateTask.mockRejectedValue(new Error("服务器繁忙，请稍后重试"));

    render(<GenerativeOutpaintPanel sessionId="sess-123" baseWidth={800} baseHeight={600} />);

    await user.click(screen.getByRole("radio", { name: "16:9" }));
    await user.click(screen.getByRole("button", { name: "开始 AI 画幅扩充" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("服务器繁忙，请稍后重试");
    });
  });

  it("satisfies axe accessibility standards", async () => {
    const { container } = render(
      <GenerativeOutpaintPanel sessionId="sess-123" baseWidth={1000} baseHeight={1000} />,
    );

    const violations = await severeViolations(container);
    expect(violations).toEqual([]);
  });
});
