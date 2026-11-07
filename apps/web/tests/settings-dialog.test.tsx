import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SettingsDialog } from "@/components/settings-dialog";
import type {
  ProviderSettingsUpdate,
  ProviderSettingsView,
  ProviderTestResponse,
} from "@/types/provider-settings";

const BASE = "/api/v1/settings/providers";

const VIEW: ProviderSettingsView = {
  vision: {
    provider: "openai",
    model: "gpt-4o",
    baseUrl: "https://vision.example.test/v1",
    hasApiKey: true,
    apiKeySource: "saved",
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
  isMock: true,
  hasSavedOverrides: true,
};

const RESET_VIEW: ProviderSettingsView = {
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
  isMock: true,
  hasSavedOverrides: false,
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function errorResponse(status: number, code: string, details: Record<string, unknown> = {}) {
  return jsonResponse({ error: { code, message: "Request failed.", details } }, status);
}

function applyPatch(
  view: ProviderSettingsView,
  update: ProviderSettingsUpdate,
): ProviderSettingsView {
  const next = structuredClone(view);
  for (const section of ["vision", "decision", "planner"] as const) {
    const patch = update[section];
    if (!patch) {
      continue;
    }
    if (patch.provider !== undefined) {
      next[section].provider = patch.provider;
    }
    if (patch.model !== undefined) {
      next[section].model = patch.model;
    }
    if (patch.baseUrl !== undefined) {
      next[section].baseUrl = patch.baseUrl;
    }
    if (patch.clearApiKey) {
      next[section].hasApiKey = false;
      next[section].apiKeySource = "none";
    } else if (patch.apiKey) {
      next[section].hasApiKey = true;
      next[section].apiKeySource = "saved";
    }
    if (next[section].provider === "mock" && !next[section].model) {
      next[section].model =
        section === "vision"
          ? "mock-vision"
          : section === "planner"
            ? "mock-planner"
            : "mock-decision";
    }
  }
  next.hasSavedOverrides = true;
  next.isMock = next.vision.provider === "mock" || next.decision.provider === "mock";
  return next;
}

function stubApi(
  handlers: {
    load?: () => Response;
    save?: (update: ProviderSettingsUpdate) => Response;
    test?: (update: ProviderSettingsUpdate) => Response;
    reset?: () => Response;
  } = {},
) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";
    if (url.endsWith(`${BASE}/reset`) && method === "POST") {
      return handlers.reset ? handlers.reset() : jsonResponse(RESET_VIEW);
    }
    if (url.endsWith(`${BASE}/test`) && method === "POST") {
      const update = JSON.parse(String(init?.body ?? "{}")) as ProviderSettingsUpdate;
      return handlers.test ? handlers.test(update) : jsonResponse(TEST_RESULTS);
    }
    if (url.endsWith(BASE) && method === "POST") {
      const update = JSON.parse(String(init?.body ?? "{}")) as ProviderSettingsUpdate;
      return handlers.save ? handlers.save(update) : jsonResponse(applyPatch(VIEW, update));
    }
    if (url.endsWith(BASE)) {
      return handlers.load ? handlers.load() : jsonResponse(VIEW);
    }
    return errorResponse(404, "not_found");
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function saveCalls(fetchMock: ReturnType<typeof stubApi>) {
  return fetchMock.mock.calls.filter(([, init]) => init?.method === "POST");
}

const TEST_RESULTS: ProviderTestResponse = {
  vision: {
    ok: true,
    provider: "openai",
    model: "gpt-4o",
    latencyMs: 123,
    code: null,
    message: null,
  },
  decision: {
    ok: false,
    provider: "openai",
    model: "gpt-4o-mini",
    latencyMs: 980,
    code: "provider_auth_error",
    message: "The model provider rejected the configured credentials.",
  },
  planner: {
    ok: true,
    provider: "mock",
    model: "mock-planner",
    latencyMs: 45,
    code: null,
    message: null,
  },
};

function renderDialog(open = true) {
  const onClose = vi.fn();
  const view = render(<SettingsDialog open={open} onClose={onClose} />);
  return { ...view, onClose };
}

async function visionGroup() {
  return screen.findByRole("group", { name: "视觉模型" });
}

describe("SettingsDialog", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads the current settings without echoing the saved key", async () => {
    stubApi();
    renderDialog();

    const vision = await visionGroup();
    expect(within(vision).getByLabelText("Provider")).toHaveValue("openai");
    expect(within(vision).getByLabelText("模型名")).toHaveValue("gpt-4o");
    expect(within(vision).getByLabelText("Base URL")).toHaveValue(
      "https://vision.example.test/v1",
    );
    expect(within(vision).getByLabelText("API Key")).toHaveValue("");
    expect(within(vision).getByLabelText("API Key")).toHaveAttribute(
      "placeholder",
      "已从本地保存，留空保持不变",
    );
    expect(within(vision).getByText(/密钥来源：本地保存/)).toBeInTheDocument();

    const decision = screen.getByRole("group", { name: "决策模型" });
    expect(within(decision).getByLabelText("Provider")).toHaveValue("mock");
    expect(within(decision).getByLabelText("模型名")).toBeDisabled();

    const planner = screen.getByRole("group", { name: "规划模型（可选）" });
    expect(within(planner).getByLabelText("Provider")).toHaveValue("mock");
    expect(within(planner).getByLabelText("模型名")).toHaveValue("mock-planner");
    expect(within(planner).getByText(/留空即跟随决策模型/)).toBeInTheDocument();
  });

  it("saves only changed fields and omits an empty apiKey", async () => {
    const fetchMock = stubApi();
    renderDialog();

    const vision = await visionGroup();
    const model = within(vision).getByLabelText("模型名");
    await userEvent.clear(model);
    await userEvent.type(model, "gpt-4o-mini");
    await userEvent.click(screen.getByRole("button", { name: "保存并应用" }));

    expect(await screen.findByText(/已保存并应用/)).toBeInTheDocument();
    const postCalls = saveCalls(fetchMock);
    expect(postCalls).toHaveLength(1);
    const payload = JSON.parse(String(postCalls[0][1]?.body));
    expect(payload).toEqual({ vision: { model: "gpt-4o-mini" } });
    expect(within(vision).getByLabelText("模型名")).toHaveValue("gpt-4o-mini");
  });

  it("saves planner-only overrides without touching the decision section", async () => {
    const fetchMock = stubApi();
    renderDialog();

    await visionGroup();
    const planner = screen.getByRole("group", { name: "规划模型（可选）" });
    await userEvent.selectOptions(within(planner).getByLabelText("Provider"), "openai");
    await userEvent.type(within(planner).getByLabelText("模型名"), "planner-model");
    await userEvent.type(within(planner).getByLabelText("Base URL"), "https://planner.test/v1");
    await userEvent.type(within(planner).getByLabelText("API Key"), "sk-planner");
    await userEvent.click(screen.getByRole("button", { name: "保存并应用" }));

    expect(await screen.findByText(/已保存并应用/)).toBeInTheDocument();
    const payload = JSON.parse(String(saveCalls(fetchMock)[0][1]?.body));
    expect(payload).toEqual({
      planner: {
        provider: "openai",
        model: "planner-model",
        baseUrl: "https://planner.test/v1",
        apiKey: "sk-planner",
      },
    });
  });

  it("submits a new api key and clears the field after saving", async () => {
    const fetchMock = stubApi();
    renderDialog();

    const vision = await visionGroup();
    await userEvent.type(within(vision).getByLabelText("API Key"), "sk-new-key");
    await userEvent.click(screen.getByRole("button", { name: "保存并应用" }));

    expect(await screen.findByText(/已保存并应用/)).toBeInTheDocument();
    const payload = JSON.parse(String(saveCalls(fetchMock)[0][1]?.body));
    expect(payload).toEqual({ vision: { apiKey: "sk-new-key" } });
    expect(within(vision).getByLabelText("API Key")).toHaveValue("");
  });

  it("requests removal of a saved key through clearApiKey", async () => {
    const fetchMock = stubApi();
    renderDialog();

    const vision = await visionGroup();
    await userEvent.click(within(vision).getByLabelText("清除已保存密钥"));
    await userEvent.click(screen.getByRole("button", { name: "保存并应用" }));

    expect(await screen.findByText(/已保存并应用/)).toBeInTheDocument();
    const payload = JSON.parse(String(saveCalls(fetchMock)[0][1]?.body));
    expect(payload).toEqual({ vision: { clearApiKey: true } });
  });

  it("tests the connection with the current form values without saving", async () => {
    const fetchMock = stubApi();
    renderDialog();

    await visionGroup();
    await userEvent.click(screen.getByRole("button", { name: "测试连接" }));

    expect(await screen.findByText(/视觉模型：连接正常（123 ms）/)).toBeInTheDocument();
    expect(
      screen.getByText(/决策模型：连接失败（provider_auth_error）/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/规划模型（可选）：连接正常（45 ms）/),
    ).toBeInTheDocument();
    expect(screen.getByText(/不会上传图片/)).toBeInTheDocument();

    const postCalls = saveCalls(fetchMock);
    expect(postCalls).toHaveLength(1);
    expect(String(postCalls[0][0])).toContain("/settings/providers/test");
    expect(JSON.parse(String(postCalls[0][1]?.body))).toEqual({});
  });

  it("requires confirmation before resetting to environment settings", async () => {
    const fetchMock = stubApi();
    renderDialog();

    await visionGroup();
    await userEvent.click(screen.getByRole("button", { name: "恢复环境变量配置" }));
    expect(screen.getByText(/恢复后将删除本地保存的模型配置/)).toBeInTheDocument();
    expect(saveCalls(fetchMock)).toHaveLength(0);

    await userEvent.click(screen.getByRole("button", { name: "确认恢复" }));

    expect(await screen.findByText("已恢复环境变量配置。")).toBeInTheDocument();
    const postCalls = saveCalls(fetchMock);
    expect(postCalls).toHaveLength(1);
    expect(String(postCalls[0][0])).toContain("/settings/providers/reset");
    const vision = screen.getByRole("group", { name: "视觉模型" });
    expect(within(vision).getByLabelText("Provider")).toHaveValue("mock");
    expect(screen.getByRole("button", { name: "恢复环境变量配置" })).toBeDisabled();
  });

  it("shows invalid field names returned by the API", async () => {
    stubApi({
      save: () =>
        errorResponse(422, "invalid_provider_settings", {
          fields: [
            { field: "vision.apiKey", rule: "missing", limit: {}, message: "Required." },
            { field: "vision.model", rule: "missing", limit: {}, message: "Required." },
          ],
        }),
    });
    renderDialog();

    const vision = await visionGroup();
    await userEvent.clear(within(vision).getByLabelText("模型名"));
    await userEvent.type(within(vision).getByLabelText("模型名"), "another-model");
    await userEvent.click(screen.getByRole("button", { name: "保存并应用" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "配置不完整或格式不正确：vision.apiKey、vision.model",
    );
    expect(screen.getByRole("dialog", { name: "模型设置" })).toBeInTheDocument();
  });

  it("offers a retry when loading fails", async () => {
    let attempts = 0;
    stubApi({
      load: () => {
        attempts += 1;
        return attempts === 1
          ? errorResponse(503, "provider_settings_unavailable")
          : jsonResponse(VIEW);
      },
    });
    renderDialog();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("设置服务尚未就绪，请稍后重试。");

    await userEvent.click(screen.getByRole("button", { name: "重新读取" }));
    const vision = await visionGroup();
    expect(within(vision).getByLabelText("模型名")).toHaveValue("gpt-4o");
  });

  it("renders nothing while closed and closes on Escape", async () => {
    stubApi();
    const { onClose, rerender } = renderDialog(false);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    rerender(<SettingsDialog open onClose={onClose} />);
    await visionGroup();
    await userEvent.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("has no serious or critical axe violations", async () => {
    stubApi();
    const { container } = renderDialog();
    await visionGroup();

    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    const severe = results.violations.filter(
      (violation) => violation.impact === "serious" || violation.impact === "critical",
    );

    expect(severe).toEqual([]);
  });
});
