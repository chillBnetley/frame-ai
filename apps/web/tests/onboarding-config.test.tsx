import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfigStage } from "@/features/onboarding/components/config-stage";
import type {
  ProviderSettingsView,
  ProviderTestResponse,
} from "@/types/provider-settings";

const settingsApi = vi.hoisted(() => ({
  fetchProviderSettings: vi.fn(),
  saveProviderSettings: vi.fn(),
  testProviderSettings: vi.fn(),
}));

vi.mock("@/lib/api/settings", () => settingsApi);

const MOCK_VIEW: ProviderSettingsView = {
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

const OPENAI_VISION_VIEW: ProviderSettingsView = {
  ...MOCK_VIEW,
  vision: {
    provider: "openai",
    model: "gpt-4o",
    baseUrl: "https://api.example.com/v1",
    hasApiKey: false,
    apiKeySource: "none",
  },
  isMock: true,
};

const OPENAI_VISION_SAVED_VIEW: ProviderSettingsView = {
  ...OPENAI_VISION_VIEW,
  vision: {
    ...OPENAI_VISION_VIEW.vision,
    hasApiKey: true,
    apiKeySource: "saved",
  },
};

const DECISION_SAVED_VIEW: ProviderSettingsView = {
  ...OPENAI_VISION_SAVED_VIEW,
  decision: {
    provider: "openai",
    model: "gpt-4o",
    baseUrl: "https://api.example.com/v1",
    hasApiKey: true,
    apiKeySource: "saved",
  },
  isMock: false,
};

const ENV_VISION_VIEW: ProviderSettingsView = {
  ...OPENAI_VISION_VIEW,
  vision: {
    ...OPENAI_VISION_VIEW.vision,
    hasApiKey: true,
    apiKeySource: "environment",
  },
};

const TEST_RESULTS: ProviderTestResponse = {
  vision: {
    ok: true,
    provider: "openai",
    model: "gpt-4o",
    latencyMs: 120,
  },
  decision: {
    ok: true,
    provider: "mock",
    model: "mock-decision",
    latencyMs: 8,
  },
  planner: {
    ok: true,
    provider: "mock",
    model: "mock-planner",
    latencyMs: 7,
  },
  generative: {
    ok: true,
    provider: "mock",
    model: "wanx2.1-imageedit",
    latencyMs: 6,
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

function renderConfig() {
  const onComplete = vi.fn();
  const onSkip = vi.fn();
  const utils = render(
    <ConfigStage onComplete={onComplete} onSkip={onSkip} />,
  );
  return { ...utils, onComplete, onSkip };
}

beforeEach(() => {
  settingsApi.fetchProviderSettings.mockReset();
  settingsApi.saveProviderSettings.mockReset();
  settingsApi.testProviderSettings.mockReset();
});

describe("ConfigStage", () => {
  it("renders the current vision configuration", async () => {
    settingsApi.fetchProviderSettings.mockResolvedValue(OPENAI_VISION_VIEW);
    renderConfig();

    expect(await screen.findByDisplayValue("gpt-4o")).toBeInTheDocument();
    expect(screen.getByLabelText("Provider")).toHaveValue("openai");
    expect(screen.getByLabelText("Base URL")).toHaveValue(
      "https://api.example.com/v1",
    );
    expect(
      screen.getByRole("heading", { name: "视觉模型" }),
    ).toBeInTheDocument();
  });

  it("requires an API key before continuing", async () => {
    settingsApi.fetchProviderSettings.mockResolvedValue(OPENAI_VISION_VIEW);
    const user = userEvent.setup();
    renderConfig();
    await screen.findByDisplayValue("gpt-4o");

    await user.click(screen.getByRole("button", { name: "下一步" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "视觉模型：请填写 API Key。",
    );
    expect(settingsApi.saveProviderSettings).not.toHaveBeenCalled();
    expect(
      screen.getByRole("heading", { name: "视觉模型" }),
    ).toBeInTheDocument();
  });

  it("saves the vision key and reuses it for the decision model", async () => {
    settingsApi.fetchProviderSettings.mockResolvedValue(OPENAI_VISION_VIEW);
    settingsApi.saveProviderSettings
      .mockResolvedValueOnce(OPENAI_VISION_SAVED_VIEW)
      .mockResolvedValueOnce(DECISION_SAVED_VIEW);
    const user = userEvent.setup();
    renderConfig();
    await screen.findByDisplayValue("gpt-4o");

    await user.type(screen.getByLabelText("API Key"), "sk-test");
    await user.click(screen.getByRole("button", { name: "下一步" }));

    await waitFor(() =>
      expect(settingsApi.saveProviderSettings).toHaveBeenNthCalledWith(1, {
        vision: { apiKey: "sk-test" },
      }),
    );
    expect(
      await screen.findByRole("heading", { name: "决策模型" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "暂不配置" }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("API Key")).toHaveAttribute(
      "placeholder",
      "已使用上一步输入的密钥，留空沿用",
    );

    await user.click(screen.getByRole("button", { name: "下一步" }));

    await waitFor(() =>
      expect(settingsApi.saveProviderSettings).toHaveBeenNthCalledWith(2, {
        decision: {
          provider: "openai",
          model: "gpt-4o",
          baseUrl: "https://api.example.com/v1",
          apiKey: "sk-test",
        },
      }),
    );
    expect(
      await screen.findByRole("heading", { name: "生成式图像" }),
    ).toBeInTheDocument();
  });

  it("explains that a saved vision key cannot be reused automatically", async () => {
    settingsApi.fetchProviderSettings.mockResolvedValue(ENV_VISION_VIEW);
    const user = userEvent.setup();
    renderConfig();
    await screen.findByDisplayValue("gpt-4o");

    await user.click(screen.getByRole("button", { name: "下一步" }));

    expect(
      await screen.findByRole("heading", { name: "决策模型" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/视觉模型的密钥已保存在本机/),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "下一步" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "决策模型：请填写 API Key。",
    );
  });

  it("keeps the inherited connection when editing the decision model", async () => {
    settingsApi.fetchProviderSettings.mockResolvedValue(ENV_VISION_VIEW);
    const user = userEvent.setup();
    renderConfig();
    await screen.findByDisplayValue("gpt-4o");

    await user.click(screen.getByRole("button", { name: "下一步" }));
    await screen.findByRole("heading", { name: "决策模型" });

    const modelInput = screen.getByLabelText("模型名");
    expect(modelInput).toHaveValue("gpt-4o");
    await user.clear(modelInput);
    await user.type(modelInput, "gpt-4o-mini");

    expect(screen.getByLabelText("Provider")).toHaveValue("openai");
    expect(screen.getByLabelText("Base URL")).toHaveValue(
      "https://api.example.com/v1",
    );
  });

  it("can skip the remaining configuration", async () => {
    settingsApi.fetchProviderSettings.mockResolvedValue(MOCK_VIEW);
    const user = userEvent.setup();
    const { onSkip } = renderConfig();
    await screen.findByLabelText("模型名");

    await user.click(screen.getByRole("button", { name: "暂不配置" }));

    expect(onSkip).toHaveBeenCalledWith(false);
  });

  it("shows the connection test result", async () => {
    settingsApi.fetchProviderSettings.mockResolvedValue(ENV_VISION_VIEW);
    settingsApi.testProviderSettings.mockResolvedValue(TEST_RESULTS);
    const user = userEvent.setup();
    renderConfig();
    await screen.findByDisplayValue("gpt-4o");

    await user.click(screen.getByRole("button", { name: "测试连接" }));

    expect(await screen.findByText("连接正常（120 ms）")).toBeInTheDocument();
  });

  it("saves the optional DashScope configuration", async () => {
    settingsApi.fetchProviderSettings.mockResolvedValue(MOCK_VIEW);
    settingsApi.saveProviderSettings.mockResolvedValue(MOCK_VIEW);
    const user = userEvent.setup();
    const { onComplete } = renderConfig();
    await screen.findByLabelText("模型名");

    await user.click(screen.getByRole("button", { name: "下一步" }));
    await screen.findByRole("heading", { name: "决策模型" });
    await user.click(screen.getByRole("button", { name: "下一步" }));
    await screen.findByRole("heading", { name: "生成式图像" });

    await user.selectOptions(screen.getByLabelText("Provider"), "dashscope");
    await user.type(screen.getByLabelText("API Key（百炼）"), "sk-dash");
    await user.click(screen.getByRole("button", { name: "完成" }));

    await waitFor(() =>
      expect(settingsApi.saveProviderSettings).toHaveBeenCalledWith({
        generative: { provider: "dashscope", apiKey: "sk-dash" },
      }),
    );
    await waitFor(() => expect(onComplete).toHaveBeenCalledWith(false));
  });

  it("shows a load error and still allows skipping", async () => {
    settingsApi.fetchProviderSettings.mockRejectedValue(new Error("boom"));
    const user = userEvent.setup();
    const { onSkip } = renderConfig();

    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
    expect(
      screen.getByRole("button", { name: "重新读取" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "暂不配置" }));

    expect(onSkip).toHaveBeenCalledWith(false);
  });

  it("has no serious or critical axe violations", async () => {
    settingsApi.fetchProviderSettings.mockResolvedValue(OPENAI_VISION_VIEW);
    const { container } = renderConfig();
    await screen.findByDisplayValue("gpt-4o");

    expect(await severeViolations(container)).toEqual([]);
  });
});
