import { act, renderHook } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ANALYSIS_FAST_POLL_MS,
  ANALYSIS_SLOW_POLL_MS,
  useAnalysis,
} from "@/features/analysis/hooks/use-analysis";
import type {
  AnalysisStatusResponse,
  AnalysisTaskCreated,
} from "@/types/analysis";
import {
  analysisReport,
  analysisStatus,
  ANALYSIS_ID,
  ANALYSIS_OTHER_IMAGE_ID,
} from "./analysis-fixtures";
import { IMAGE_ID } from "./session-fixtures";

const CREATED: AnalysisTaskCreated = {
  analysisId: ANALYSIS_ID,
  status: "pending",
  stage: "queued",
  deduplicated: false,
};

type StatusSource =
  | AnalysisStatusResponse
  | Response
  | (() =>
      | AnalysisStatusResponse
      | Response
      | Promise<AnalysisStatusResponse | Response>);

interface RecordedCall {
  kind: "create" | "status" | "result";
  body?: Record<string, unknown>;
  signal?: AbortSignal;
  at: number;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function installApi(options: {
  statuses: StatusSource[];
  result?: () => Promise<Response> | Response;
}) {
  const calls: RecordedCall[] = [];
  let statusIndex = 0;
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/api/v1/analysis") && method === "POST") {
        calls.push({
          kind: "create",
          body: JSON.parse(String(init?.body)) as Record<string, unknown>,
          signal: init?.signal ?? undefined,
          at: Date.now(),
        });
        return json(CREATED);
      }
      if (url.endsWith("/result") && method === "GET") {
        calls.push({
          kind: "result",
          signal: init?.signal ?? undefined,
          at: Date.now(),
        });
        return options.result
          ? await options.result()
          : json(analysisReport());
      }
      if (url.includes(`/api/v1/analysis/${ANALYSIS_ID}`) && method === "GET") {
        calls.push({
          kind: "status",
          signal: init?.signal ?? undefined,
          at: Date.now(),
        });
        const source =
          options.statuses[
            Math.min(statusIndex, options.statuses.length - 1)
          ];
        statusIndex += 1;
        const value = typeof source === "function" ? await source() : source;
        return value instanceof Response ? value : json(value);
      }
      return json(
        { error: { code: "not_found", message: "Not found", details: {} } },
        404,
      );
    },
  );
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, calls };
}

function count(calls: RecordedCall[], kind: RecordedCall["kind"]): number {
  return calls.filter((call) => call.kind === kind).length;
}

async function flush(): Promise<void> {
  for (let index = 0; index < 10; index += 1) {
    await Promise.resolve();
  }
}

interface HookHandle {
  result: { current: ReturnType<typeof useAnalysis> };
  rerender?: (props: { imageId: string }) => void;
}

async function start(hook: HookHandle): Promise<void> {
  await act(async () => {
    hook.result.current.start();
    await flush();
  });
}

async function tick(milliseconds: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(milliseconds);
  });
}

async function rerenderWith(
  hook: HookHandle,
  imageId: string,
): Promise<void> {
  await act(async () => {
    hook.rerender?.({ imageId });
    await flush();
  });
}

function lastOf<T>(values: readonly T[]): T | undefined {
  return values.length > 0 ? values[values.length - 1] : undefined;
}

const PROCESSING = analysisStatus({
  status: "processing",
  stage: "vision",
  startedAt: "2026-11-03T00:00:01Z",
});

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-03T00:00:00Z"));
  window.localStorage.clear();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    value: "visible",
  });
});

describe("useAnalysis", () => {
  it("polls every second for ten seconds and then backs off to two seconds", async () => {
    const origin = Date.now();
    const { calls } = installApi({ statuses: [PROCESSING] });
    const hook = renderHook(() => useAnalysis(IMAGE_ID));

    await start(hook);
    expect(hook.result.current.status).toBe("pending");
    expect(count(calls, "status")).toBe(0);

    await tick(11_999);
    const times = calls
      .filter((call) => call.kind === "status")
      .map((call) => call.at - origin);
    expect(times).toEqual([
      ANALYSIS_FAST_POLL_MS * 1,
      ANALYSIS_FAST_POLL_MS * 2,
      ANALYSIS_FAST_POLL_MS * 3,
      ANALYSIS_FAST_POLL_MS * 4,
      ANALYSIS_FAST_POLL_MS * 5,
      ANALYSIS_FAST_POLL_MS * 6,
      ANALYSIS_FAST_POLL_MS * 7,
      ANALYSIS_FAST_POLL_MS * 8,
      ANALYSIS_FAST_POLL_MS * 9,
      ANALYSIS_FAST_POLL_MS * 10,
    ]);

    await tick(1);
    const last = lastOf(calls.filter((call) => call.kind === "status"));
    expect(last?.at).toBe(origin + ANALYSIS_FAST_POLL_MS * 10 + ANALYSIS_SLOW_POLL_MS);
  });

  it("stops polling and exposes the report once completed", async () => {
    const { calls } = installApi({
      statuses: [
        analysisStatus({
          status: "completed",
          stage: "completed",
          resultAvailable: true,
          result: analysisReport(),
          completedAt: "2026-11-03T00:00:05Z",
        }),
      ],
    });
    const hook = renderHook(() => useAnalysis(IMAGE_ID));

    await start(hook);
    await tick(ANALYSIS_FAST_POLL_MS);

    expect(hook.result.current.status).toBe("completed");
    expect(hook.result.current.report?.analysisId).toBe(ANALYSIS_ID);
    expect(hook.result.current.running).toBe(false);

    const statusCalls = count(calls, "status");
    await tick(10_000);
    expect(count(calls, "status")).toBe(statusCalls);
  });

  it("fetches the result endpoint when the status has no embedded result", async () => {
    const { calls } = installApi({
      statuses: [
        analysisStatus({
          status: "completed",
          stage: "completed",
          resultAvailable: true,
          result: null,
        }),
      ],
    });
    const hook = renderHook(() => useAnalysis(IMAGE_ID));

    await start(hook);
    await tick(ANALYSIS_FAST_POLL_MS);

    expect(count(calls, "result")).toBe(1);
    expect(hook.result.current.report?.analysisId).toBe(ANALYSIS_ID);
  });

  it("reports provider failures and reuses the same task when retrying", async () => {
    const failed = analysisStatus({
      status: "failed",
      stage: "failed",
      error: { code: "provider_unavailable", message: "视觉模型暂时不可用。" },
    });
    const { calls } = installApi({ statuses: [failed] });
    const hook = renderHook(() => useAnalysis(IMAGE_ID));

    await start(hook);
    await tick(ANALYSIS_FAST_POLL_MS);

    expect(hook.result.current.status).toBe("failed");
    expect(hook.result.current.error?.code).toBe("provider_unavailable");

    await act(async () => {
      hook.result.current.retry();
      await flush();
    });
    const createCalls = calls.filter((call) => call.kind === "create");
    expect(createCalls).toHaveLength(2);
    expect(createCalls[1]?.body).toEqual({ imageId: IMAGE_ID, force: false });
  });

  it("maps a queued budget failure code to Chinese copy", async () => {
    const failed = analysisStatus({
      status: "failed",
      stage: "failed",
      error: {
        code: "provider_budget_exceeded",
        message: "The daily model usage limit has been reached.",
      },
    });
    const { calls } = installApi({ statuses: [failed] });
    const hook = renderHook(() => useAnalysis(IMAGE_ID));

    await start(hook);
    await tick(ANALYSIS_FAST_POLL_MS);

    expect(count(calls, "status")).toBeGreaterThan(0);
    expect(hook.result.current.error?.code).toBe("provider_budget_exceeded");
    expect(hook.result.current.error?.message).toBe(
      "已达到今日模型调用上限，请明天再试或调高每日限额。",
    );
  });

  it("keeps the previous report visible while a forced rerun is running", async () => {
    const { calls } = installApi({
      statuses: [
        analysisStatus({
          status: "completed",
          stage: "completed",
          resultAvailable: true,
          result: analysisReport(),
        }),
        PROCESSING,
      ],
    });
    const hook = renderHook(() => useAnalysis(IMAGE_ID));

    await start(hook);
    await tick(ANALYSIS_FAST_POLL_MS);
    expect(hook.result.current.report).not.toBeNull();

    await act(async () => {
      hook.result.current.rerun();
      await flush();
    });
    expect(hook.result.current.report?.analysisId).toBe(ANALYSIS_ID);
    expect(hook.result.current.running).toBe(true);

    const createCalls = calls.filter((call) => call.kind === "create");
    expect(lastOf(createCalls)?.body).toEqual({
      imageId: IMAGE_ID,
      force: true,
    });
  });

  it("aborts polling and clears state immediately when the image changes", async () => {
    const { calls } = installApi({
      statuses: [() => new Promise<AnalysisStatusResponse>(() => {})],
    });
    const hook = renderHook(({ imageId }) => useAnalysis(imageId), {
      initialProps: { imageId: IMAGE_ID },
    });

    await start(hook);
    await tick(ANALYSIS_FAST_POLL_MS);
    const inFlight = calls.find((call) => call.kind === "status");
    expect(inFlight?.signal?.aborted).toBe(false);

    await rerenderWith(hook, ANALYSIS_OTHER_IMAGE_ID);

    expect(inFlight?.signal?.aborted).toBe(true);
    expect(hook.result.current.status).toBeNull();
    expect(hook.result.current.report).toBeNull();
  });

  it("does not expose a report for another image", async () => {
    const foreign = analysisReport({
      image: { ...analysisReport().image, id: ANALYSIS_OTHER_IMAGE_ID },
    });
    installApi({
      statuses: [
        analysisStatus({
          status: "completed",
          stage: "completed",
          resultAvailable: true,
          result: foreign,
        }),
      ],
    });
    const hook = renderHook(() => useAnalysis(IMAGE_ID));

    await start(hook);
    await tick(ANALYSIS_FAST_POLL_MS);

    expect(hook.result.current.report).toBeNull();
    expect(hook.result.current.error?.code).toBe("analysis_mismatch");
  });

  it("stores the running task so a remount can resume it", async () => {
    const storageKey = `frame-ai:analysis:${IMAGE_ID}`;
    installApi({ statuses: [PROCESSING] });
    const hook = renderHook(() => useAnalysis(IMAGE_ID));

    await start(hook);

    const stored = window.localStorage.getItem(storageKey);
    expect(stored).not.toBeNull();
    expect(JSON.parse(stored ?? "{}")).toMatchObject({
      analysisId: ANALYSIS_ID,
    });
    expect(hook.result.current.startedAt).toBe(Date.now());
  });

  it("resumes a stored task after a remount and clears it on completion", async () => {
    const storageKey = `frame-ai:analysis:${IMAGE_ID}`;
    window.localStorage.setItem(
      storageKey,
      JSON.stringify({ analysisId: ANALYSIS_ID, startedAt: Date.now() - 3_000 }),
    );
    const { calls } = installApi({
      statuses: [
        analysisStatus({
          status: "completed",
          stage: "completed",
          resultAvailable: true,
          result: analysisReport(),
        }),
      ],
    });
    const hook = renderHook(() => useAnalysis(IMAGE_ID));

    await act(async () => {
      await flush();
    });

    expect(count(calls, "status")).toBe(1);
    expect(hook.result.current.status).toBe("completed");
    expect(hook.result.current.report?.analysisId).toBe(ANALYSIS_ID);
    expect(window.localStorage.getItem(storageKey)).toBeNull();
  });

  it("keeps polling after Strict Mode runs the effects twice", async () => {
    const storageKey = `frame-ai:analysis:${IMAGE_ID}`;
    window.localStorage.setItem(
      storageKey,
      JSON.stringify({ analysisId: ANALYSIS_ID, startedAt: Date.now() - 3_000 }),
    );
    const { calls } = installApi({ statuses: [PROCESSING] });
    renderHook(() => useAnalysis(IMAGE_ID), { wrapper: StrictMode });

    await act(async () => {
      await flush();
    });
    expect(count(calls, "status")).toBeGreaterThanOrEqual(1);

    await tick(ANALYSIS_FAST_POLL_MS);
    expect(count(calls, "status")).toBeGreaterThanOrEqual(2);
  });

  it("drops a stored task that the backend no longer knows", async () => {
    const storageKey = `frame-ai:analysis:${IMAGE_ID}`;
    window.localStorage.setItem(
      storageKey,
      JSON.stringify({ analysisId: ANALYSIS_ID, startedAt: Date.now() - 3_000 }),
    );
    installApi({
      statuses: [
        () =>
          json(
            {
              error: {
                code: "analysis_not_found",
                message: "Not found",
                details: {},
              },
            },
            404,
          ),
      ],
    });
    const hook = renderHook(() => useAnalysis(IMAGE_ID));

    await act(async () => {
      await flush();
    });

    expect(hook.result.current.status).toBeNull();
    expect(hook.result.current.error).toBeNull();
    expect(window.localStorage.getItem(storageKey)).toBeNull();
  });

  it("ignores a stored task older than a day", async () => {
    const storageKey = `frame-ai:analysis:${IMAGE_ID}`;
    window.localStorage.setItem(
      storageKey,
      JSON.stringify({
        analysisId: ANALYSIS_ID,
        startedAt: Date.now() - 25 * 60 * 60 * 1_000,
      }),
    );
    const { calls } = installApi({ statuses: [PROCESSING] });
    const hook = renderHook(() => useAnalysis(IMAGE_ID));

    await act(async () => {
      await flush();
    });

    expect(count(calls, "status")).toBe(0);
    expect(hook.result.current.status).toBeNull();
    expect(window.localStorage.getItem(storageKey)).toBeNull();
  });

  it("pauses polling while the page is hidden and queries immediately on resume", async () => {
    const { calls } = installApi({ statuses: [PROCESSING] });
    const hook = renderHook(() => useAnalysis(IMAGE_ID));

    await start(hook);
    await tick(ANALYSIS_FAST_POLL_MS);
    expect(count(calls, "status")).toBe(1);

    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "hidden",
    });
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await flush();
    });
    await tick(5_000);
    expect(count(calls, "status")).toBe(1);

    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await flush();
    });
    expect(count(calls, "status")).toBe(2);
  });
});