import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { INTRO_AUTO_ADVANCE_MS } from "@/features/onboarding/components/intro-stage";
import { OnboardingFlow } from "@/features/onboarding/onboarding-flow";
import type { ProviderSettingsView } from "@/types/provider-settings";

const router = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn() }));
const settingsApi = vi.hoisted(() => ({
  fetchProviderSettings: vi.fn(),
  saveProviderSettings: vi.fn(),
  testProviderSettings: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => router,
}));

vi.mock("@/lib/api/settings", () => settingsApi);

const VIEW: ProviderSettingsView = {
  vision: {
    provider: "mock",
    model: "mock-vision",
    baseUrl: "",
    hasApiKey: false,
    apiKeySource: "none",
  },
  decision: {
    provider: "mock",
    model: "mock-decision",
    baseUrl: "",
    hasApiKey: false,
    apiKeySource: "none",
  },
  planner: {
    provider: "mock",
    model: "mock-planner",
    baseUrl: "",
    hasApiKey: false,
    apiKeySource: "none",
  },
  generative: {
    provider: "mock",
    model: "wanx2.1-imageedit",
    baseUrl: "",
    hasApiKey: false,
    apiKeySource: "none",
    dailyImageLimit: 0,
    ready: true,
  },
  isMock: true,
  hasSavedOverrides: false,
};

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
  settingsApi.fetchProviderSettings.mockReset().mockResolvedValue(VIEW);
  settingsApi.saveProviderSettings.mockReset().mockResolvedValue(VIEW);
  settingsApi.testProviderSettings.mockReset();
});

afterEach(() => {
  document.cookie = "frame_onboarding_session=; Path=/; Max-Age=0";
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("OnboardingFlow", () => {
  it("shows the intro copy", () => {
    render(<OnboardingFlow />);

    expect(
      screen.getByRole("heading", { name: "私人 AI 摄影大师" }),
    ).toBeInTheDocument();
    expect(screen.getByText("FRAME AI")).toBeInTheDocument();
  });

  it("moves from the intro to the config step and can skip to the finale", async () => {
    const user = userEvent.setup();
    render(<OnboardingFlow />);

    await user.click(screen.getByRole("button", { name: "继续" }));

    expect(
      screen.getByRole("heading", { name: "视觉模型" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "暂不配置" }));

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
      screen.getByRole("heading", { name: "视觉模型" }),
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
    await user.click(screen.getByRole("button", { name: "暂不配置" }));
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
    await user.click(screen.getByRole("button", { name: "暂不配置" }));
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
    await user.click(screen.getByRole("button", { name: "暂不配置" }));
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

  it("has no serious or critical axe violations on the config step", async () => {
    const user = userEvent.setup();
    const { container } = render(<OnboardingFlow />);

    await user.click(screen.getByRole("button", { name: "继续" }));
    await screen.findByLabelText("模型名");

    expect(await severeViolations(container)).toEqual([]);
  });

  it("has no serious or critical axe violations on the finale", async () => {
    const user = userEvent.setup();
    const { container } = render(<OnboardingFlow />);

    await user.click(screen.getByRole("button", { name: "继续" }));
    await user.click(screen.getByRole("button", { name: "暂不配置" }));

    expect(await severeViolations(container)).toEqual([]);
  });
});
