import { act, render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PreviewMonitor } from "@/features/editor/components/preview-monitor";
import { usePreviewVisibility } from "@/features/editor/hooks/use-preview-visibility";
import type { PreviewState } from "@/features/editor/state/editor-reducer";

const PREVIEW: PreviewState = {
  url: "/api/v1/previews/mocked-preview",
  width: 800,
  height: 600,
  quality: "draft",
  status: "ready",
  seq: 1,
  version: 1,
  error: null,
  warnings: [],
};

const observers: FakeIntersectionObserver[] = [];

class FakeIntersectionObserver {
  readonly observe = vi.fn();
  readonly disconnect = vi.fn();
  readonly unobserve = vi.fn();
  readonly takeRecords = vi.fn(() => []);

  constructor(private readonly callback: IntersectionObserverCallback) {
    observers.push(this);
  }

  trigger(isIntersecting: boolean): void {
    const entry = { isIntersecting } as IntersectionObserverEntry;
    this.callback([entry], this as unknown as IntersectionObserver);
  }
}

beforeEach(() => {
  observers.length = 0;
  vi.stubGlobal("IntersectionObserver", FakeIntersectionObserver);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("usePreviewVisibility", () => {
  it("switches from visible to hidden when the observed preview leaves the viewport", () => {
    const { result } = renderHook(() => usePreviewVisibility());

    expect(result.current.isVisible).toBe(true);

    const element = document.createElement("div");
    act(() => result.current.sentinelRef(element));

    expect(observers).toHaveLength(1);
    expect(observers[0]?.observe).toHaveBeenCalledWith(element);

    act(() => observers[0]?.trigger(false));
    expect(result.current.isVisible).toBe(false);

    act(() => observers[0]?.trigger(true));
    expect(result.current.isVisible).toBe(true);
  });

  it("disconnects the observer when the sentinel unmounts", () => {
    const { result } = renderHook(() => usePreviewVisibility());
    const element = document.createElement("div");
    act(() => result.current.sentinelRef(element));

    act(() => result.current.sentinelRef(null));

    expect(observers[0]?.disconnect).toHaveBeenCalled();
  });
});

describe("PreviewMonitor", () => {
  it("shows a single return control with a decorative image", async () => {
    const onReturn = vi.fn();
    render(<PreviewMonitor preview={PREVIEW} visible onReturn={onReturn} />);

    const monitor = screen.getByTestId("preview-monitor");
    expect(monitor).toBeInTheDocument();
    expect(screen.queryByAltText("编辑后的预览")).not.toBeInTheDocument();
    expect(monitor.querySelector("img")).toHaveAttribute("alt", "");

    await userEvent.click(screen.getByRole("button", { name: "返回编辑预览" }));
    expect(onReturn).toHaveBeenCalledTimes(1);
  });

  it("stays hidden when the main preview is visible or no preview exists", () => {
    const { rerender } = render(
      <PreviewMonitor preview={PREVIEW} visible={false} onReturn={vi.fn()} />,
    );
    expect(screen.queryByTestId("preview-monitor")).not.toBeInTheDocument();

    rerender(<PreviewMonitor preview={{ ...PREVIEW, url: null }} visible onReturn={vi.fn()} />);
    expect(screen.queryByTestId("preview-monitor")).not.toBeInTheDocument();
  });

  it("has no serious or critical axe violations", async () => {
    render(<PreviewMonitor preview={PREVIEW} visible onReturn={vi.fn()} />);

    const results = await axe.run(document.body, {
      rules: { "color-contrast": { enabled: false } },
    });
    const severe = results.violations.filter(
      (violation) => violation.impact === "serious" || violation.impact === "critical",
    );

    expect(severe).toEqual([]);
  });
});
