import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { INTRO_AUTO_ADVANCE_MS } from "@/features/onboarding/components/intro-stage";
import { OnboardingFlow } from "@/features/onboarding/onboarding-flow";

const router = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => router,
}));

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

async function severeViolations(container: HTMLElement) {
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  return results.violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical",
  );
}

beforeEach(() => {
  router.replace.mockReset();
  router.push.mockReset();
});

afterEach(() => {
  document.cookie = "frame_onboarding_session=; Path=/; Max-Age=0";
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("OnboardingFlow", () => {
  it("shows the intro copy and moves to the finale", async () => {
    const user = userEvent.setup();
    render(<OnboardingFlow />);

    expect(
      screen.getByRole("heading", { name: "私人 AI 摄影大师" }),
    ).toBeInTheDocument();
    expect(screen.getByText("FRAME AI")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "继续" }));

    expect(
      screen.getByRole("heading", { name: "开始你的摄影之旅" }),
    ).toBeInTheDocument();
  });

  it("advances from the intro automatically", async () => {
    vi.useFakeTimers();
    render(<OnboardingFlow />);

    expect(
      screen.getByRole("heading", { name: "私人 AI 摄影大师" }),
    ).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(INTRO_AUTO_ADVANCE_MS);
    });

    expect(
      screen.getByRole("heading", { name: "开始你的摄影之旅" }),
    ).toBeInTheDocument();
  });

  it("does not auto-advance when reduced motion is requested", async () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({
        matches: true,
        media: "(prefers-reduced-motion: reduce)",
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    );
    vi.useFakeTimers();
    render(<OnboardingFlow />);

    await act(async () => {
      vi.advanceTimersByTime(INTRO_AUTO_ADVANCE_MS * 2);
    });

    expect(
      screen.getByRole("heading", { name: "私人 AI 摄影大师" }),
    ).toBeInTheDocument();
  });

  it("writes the completion marker and enters the workbench", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ completed: true }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<OnboardingFlow />);

    await user.click(screen.getByRole("button", { name: "继续" }));
    await user.click(screen.getByRole("button", { name: "开始" }));

    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/"));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/onboarding",
      expect.objectContaining({
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ completed: true }),
      }),
    );
  });

  it("stays on the finale page when the marker cannot be written", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({ error: "onboarding_write_failed" }, 500),
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<OnboardingFlow />);

    await user.click(screen.getByRole("button", { name: "继续" }));
    await user.click(screen.getByRole("button", { name: "开始" }));

    expect(
      await screen.findByRole("alert"),
    ).toHaveTextContent("无法写入本机引导状态");
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("offers a session-only fallback when the marker cannot be written", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({ error: "onboarding_write_failed" }, 500),
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<OnboardingFlow />);

    await user.click(screen.getByRole("button", { name: "继续" }));
    await user.click(screen.getByRole("button", { name: "开始" }));
    await screen.findByRole("alert");
    await user.click(
      screen.getByRole("button", { name: "仍然进入（本次有效）" }),
    );

    expect(router.replace).toHaveBeenCalledWith("/");
    expect(document.cookie).toContain("frame_onboarding_session=1");
  });

  it("has no serious or critical axe violations on the intro", async () => {
    const { container } = render(<OnboardingFlow />);

    expect(await severeViolations(container)).toEqual([]);
  });

  it("has no serious or critical axe violations on the finale", async () => {
    const user = userEvent.setup();
    const { container } = render(<OnboardingFlow />);

    await user.click(screen.getByRole("button", { name: "继续" }));

    expect(await severeViolations(container)).toEqual([]);
  });
});
