import { renderHook, waitFor, act } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useGenerativeTask } from "@/features/generative/use-generative-task";
import * as generativeApi from "@/lib/api/generative";
import type {
  GenerativeTaskCreated,
  GenerativeTaskStatusResponse,
} from "@/types/generative";
import type { SessionState } from "@/types/session";

vi.mock("@/lib/api/generative", () => ({
  createGenerativeTask: vi.fn(),
  pollGenerativeTask: vi.fn(),
  cancelGenerativeTask: vi.fn(),
  retryGenerativeTask: vi.fn(),
  acceptGenerativeResult: vi.fn(),
  rejectGenerativeResult: vi.fn(),
}));

const mockCreateTask = vi.mocked(generativeApi.createGenerativeTask);
const mockPollTask = vi.mocked(generativeApi.pollGenerativeTask);
const mockCancelTask = vi.mocked(generativeApi.cancelGenerativeTask);
const mockRetryTask = vi.mocked(generativeApi.retryGenerativeTask);
const mockAcceptResult = vi.mocked(generativeApi.acceptGenerativeResult);
const mockRejectResult = vi.mocked(generativeApi.rejectGenerativeResult);

const CREATED: GenerativeTaskCreated = {
  taskId: "task-001",
  status: "queued",
  stage: "queued",
  deduplicated: false,
  isMock: true,
  provider: "mock",
  model: "mock-1",
  expiresAt: "2026-11-11T00:00:00Z",
};

function statusResponse(overrides: Partial<GenerativeTaskStatusResponse> = {}) {
  const base: GenerativeTaskStatusResponse = {
    taskId: "task-001",
    taskType: "remove",
    baseMode: "base",
    status: "succeeded",
    stage: "completed",
    instruction: "remove it",
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
        warnings: ["mock_output"],
        createdAt: "2026-11-10T12:00:05Z",
      },
    ],
  };
  return { ...base, ...overrides };
}

const SESSION_STATE: SessionState = {
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

const REQUEST = {
  sessionId: "sess-123",
  taskType: "remove" as const,
  baseMode: "base" as const,
  instruction: "remove it",
  maskId: "mask-001",
  consent: true,
  params: { candidates: 1 },
};

describe("useGenerativeTask", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCreateTask.mockResolvedValue(CREATED);
    mockPollTask.mockResolvedValue(statusResponse());
  });

  it("runs create -> poll and exposes the settled task", async () => {
    mockPollTask.mockImplementation(async (_taskId, options) => {
      options?.onUpdate?.(
        statusResponse({ status: "processing", stage: "generating", results: [] }),
      );
      return statusResponse();
    });

    const { result } = renderHook(() => useGenerativeTask({ intervalMs: 10 }));

    await act(async () => {
      expect(await result.current.submit(REQUEST)).toBe(true);
    });

    expect(mockCreateTask).toHaveBeenCalledWith(REQUEST, undefined, expect.any(AbortSignal));
    expect(result.current.stage).toBe("completed");
    expect(result.current.candidates).toHaveLength(1);
    expect(result.current.isRunning).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("surfaces the task error payload when the task fails", async () => {
    mockPollTask.mockResolvedValue(
      statusResponse({
        status: "failed",
        stage: "failed",
        results: [],
        error: { code: "generative_no_visible_change", message: "生成结果与原图没有可见差异。" },
      }),
    );

    const { result } = renderHook(() => useGenerativeTask());
    await act(async () => {
      await result.current.submit(REQUEST);
    });

    expect(result.current.status).toBe("failed");
    expect(result.current.error).toBe("生成结果与原图没有可见差异。");
    expect(result.current.candidates).toEqual([]);
  });

  it("reports the API error when submission fails", async () => {
    mockCreateTask.mockRejectedValue(new Error("网络连接失败，请稍后重试"));

    const { result } = renderHook(() => useGenerativeTask());
    let ok = true;
    await act(async () => {
      ok = await result.current.submit(REQUEST);
    });

    expect(ok).toBe(false);
    expect(result.current.error).toBe("网络连接失败，请稍后重试");
    expect(result.current.isSubmitting).toBe(false);
  });

  it("applies the per-feature copy when the API gives no message", async () => {
    mockCreateTask.mockRejectedValue(new Error(""));

    const { result } = renderHook(() =>
      useGenerativeTask({ copy: { submitFailed: "提交消除任务失败，请检查网络或参数。" } }),
    );
    await act(async () => {
      await result.current.submit(REQUEST);
    });

    expect(result.current.error).toBe("提交消除任务失败，请检查网络或参数。");
  });

  it("clears the task and notifies on accept", async () => {
    const onAccepted = vi.fn();
    mockAcceptResult.mockResolvedValue(SESSION_STATE);

    const { result } = renderHook(() => useGenerativeTask({ onAccepted }));
    await act(async () => {
      await result.current.submit(REQUEST);
    });
    await act(async () => {
      expect(await result.current.accept("res-001")).toBe(true);
    });

    expect(mockAcceptResult).toHaveBeenCalledWith("res-001");
    expect(onAccepted).toHaveBeenCalledWith(SESSION_STATE);
    expect(result.current.task).toBeNull();
  });

  it("reports accept failures without dropping the candidate", async () => {
    mockAcceptResult.mockRejectedValue(new Error("采纳结果失败，版本未发生变化。"));

    const { result } = renderHook(() => useGenerativeTask());
    await act(async () => {
      await result.current.submit(REQUEST);
    });
    await act(async () => {
      expect(await result.current.accept("res-001")).toBe(false);
    });

    expect(result.current.error).toBe("采纳结果失败，版本未发生变化。");
    expect(result.current.candidates).toHaveLength(1);
  });

  it("clears the task and notifies on reject", async () => {
    const onRejected = vi.fn();
    mockRejectResult.mockResolvedValue(statusResponse().results![0]);

    const { result } = renderHook(() => useGenerativeTask({ onRejected }));
    await act(async () => {
      await result.current.submit(REQUEST);
    });
    await act(async () => {
      expect(await result.current.reject("res-001")).toBe(true);
    });

    expect(mockRejectResult).toHaveBeenCalledWith("res-001");
    expect(onRejected).toHaveBeenCalled();
    expect(result.current.task).toBeNull();
  });

  it("re-polls after a retry", async () => {
    mockPollTask
      .mockResolvedValueOnce(
        statusResponse({ status: "failed", stage: "failed", results: [] }),
      )
      .mockResolvedValueOnce(statusResponse());
    mockRetryTask.mockResolvedValue(
      statusResponse({ status: "queued", stage: "queued", results: [] }),
    );

    const { result } = renderHook(() => useGenerativeTask());
    await act(async () => {
      await result.current.submit(REQUEST);
    });
    expect(result.current.status).toBe("failed");

    await act(async () => {
      await result.current.retry();
    });

    expect(mockRetryTask).toHaveBeenCalledWith("task-001");
    expect(result.current.status).toBe("succeeded");
    expect(result.current.error).toBeNull();
  });

  it("stops polling and records the cancelled state", async () => {
    mockPollTask.mockImplementation(
      (_taskId, _options, signal) =>
        new Promise<GenerativeTaskStatusResponse>((_resolve, reject) => {
          signal?.addEventListener("abort", () => {
            reject(new DOMException("aborted", "AbortError"));
          });
        }),
    );
    mockCancelTask.mockResolvedValue(
      statusResponse({ status: "cancelled", stage: "failed", results: [] }),
    );

    const { result } = renderHook(() => useGenerativeTask());
    const submitPromise = result.current.submit(REQUEST);

    await waitFor(() => expect(mockPollTask).toHaveBeenCalled());
    await act(async () => {
      await result.current.cancel();
    });
    const submitted = await submitPromise;

    expect(mockCancelTask).toHaveBeenCalledWith("task-001");
    expect(submitted).toBe(false);
    expect(result.current.status).toBe("cancelled");
    expect(result.current.error).toBeNull();
  });

  it("aborts in-flight polling when unmounted", async () => {
    mockPollTask.mockImplementation(
      (_taskId, _options, signal) =>
        new Promise<GenerativeTaskStatusResponse>((_resolve, reject) => {
          signal?.addEventListener("abort", () => {
            reject(new DOMException("aborted", "AbortError"));
          });
        }),
    );

    const { result, unmount } = renderHook(() => useGenerativeTask());
    const submitPromise = result.current.submit(REQUEST);
    await waitFor(() => expect(mockPollTask).toHaveBeenCalled());
    unmount();

    await expect(submitPromise).resolves.toBe(false);
  });
});
