import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VisualDnaCustom } from "@/features/visual-dna/components/visual-dna-custom";

import {
  PERSONAL_STYLE_ID,
  customParseResponse,
  personalStyleDetail,
} from "./personal-style-fixtures";

const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/visual-dna/custom",
}));

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

beforeEach(() => {
  router.push.mockReset();
});

function installCustomMock(options: { failParse?: boolean } = {}) {
  const calls: Array<{ method: string; url: string; body: unknown }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body =
        typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : init?.body;
      calls.push({ method, url, body });
      if (url.endsWith("/api/v1/personal-styles/custom/parse")) {
        if (options.failParse) {
          return jsonResponse(
            {
              error: {
                code: "style_authoring_invalid_output",
                message: "无法理解这段描述。",
                details: {},
              },
            },
            502,
          );
        }
        return jsonResponse(customParseResponse());
      }
      if (url.endsWith("/api/v1/personal-styles/custom") && method === "POST") {
        return jsonResponse(personalStyleDetail(), 201);
      }
      return jsonResponse(
        { error: { code: "not_found", message: "missing", details: {} } },
        404,
      );
    }),
  );
  return calls;
}

describe("VisualDnaCustom", () => {
  it("parses, lets the user edit the draft, and saves a personal style", async () => {
    const calls = installCustomMock();
    const user = userEvent.setup();
    render(<VisualDnaCustom />);

    await user.type(screen.getByLabelText("风格名称"), "克制的城市");
    await user.type(
      screen.getByLabelText("风格描述"),
      "低饱和、偏冷，保留暗部层次，人物肤色自然。",
    );
    await user.type(
      screen.getByLabelText(/不希望出现的效果/),
      "不要过饱和，不要压黑",
    );
    await user.click(screen.getByRole("button", { name: /解析风格/ }));

    expect(await screen.findByRole("heading", { name: "AI 理解的风格" })).toBeInTheDocument();
    expect(screen.getByText(/mock \/ mock-planner/)).toBeInTheDocument();
    expect(screen.getByText(/识别到低饱和/)).toBeInTheDocument();
    expect(screen.getByDisplayValue("保留暗部层次")).toBeInTheDocument();

    const parsed = calls.find((call) => call.url.endsWith("/custom/parse"));
    expect(parsed?.body).toMatchObject({
      name: "克制的城市",
      avoid: "不要过饱和，不要压黑",
    });

    const confirmedName = screen.getByLabelText("确认后的名称");
    await user.clear(confirmedName);
    await user.type(confirmedName, "确认后的城市");
    await user.click(screen.getByRole("button", { name: "保存个人风格" }));

    await waitFor(() =>
      expect(router.push).toHaveBeenCalledWith(`/visual-dna/${PERSONAL_STYLE_ID}`),
    );
    const saved = calls.find(
      (call) => call.method === "POST" && call.url.endsWith("/custom"),
    );
    expect(saved?.body).toMatchObject({
      draft: { name: "确认后的城市" },
    });
  });

  it("shows a provider error and keeps the form", async () => {
    installCustomMock({ failParse: true });
    const user = userEvent.setup();
    render(<VisualDnaCustom />);

    await user.type(screen.getByLabelText("风格名称"), "测试风格");
    await user.type(screen.getByLabelText("风格描述"), "低饱和。");
    await user.click(screen.getByRole("button", { name: /解析风格/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("无法理解这段描述");
    expect(screen.getByRole("button", { name: /解析风格/ })).toBeEnabled();
  });
});
