import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VisualDnaMix } from "@/features/visual-dna/components/visual-dna-mix";

import { styleDetail, styleItem } from "./master-vision-fixtures";
import {
  PERSONAL_STYLE_ID,
  personalStyleDetail,
  personalStyleItem,
  styleMixPreview,
} from "./personal-style-fixtures";

const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/visual-dna/mix",
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

function installMixMock(options: { failPreview?: boolean } = {}) {
  const calls: Array<{ method: string; url: string; body: unknown }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body =
        typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : init?.body;
      calls.push({ method, url, body });
      if (url.endsWith("/api/v1/styles") && method === "GET") {
        return jsonResponse({ styles: [styleItem()] });
      }
      if (url.endsWith("/api/v1/personal-styles") && method === "GET") {
        return jsonResponse({ styles: [personalStyleItem()] });
      }
      if (url.endsWith("/api/v1/styles/fan_ho") && method === "GET") {
        return jsonResponse(styleDetail());
      }
      if (url.endsWith(`/api/v1/personal-styles/${PERSONAL_STYLE_ID}`) && method === "GET") {
        return jsonResponse(personalStyleDetail());
      }
      if (url.endsWith("/api/v1/style-mixes/preview")) {
        if (options.failPreview) {
          return jsonResponse(
            { error: { code: "style_not_found", message: "风格不存在。", details: {} } },
            404,
          );
        }
        return jsonResponse(styleMixPreview());
      }
      if (url.endsWith("/api/v1/style-mixes") && method === "POST") {
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

async function selectStyles(user: ReturnType<typeof userEvent.setup>) {
  const pickerA = screen.getByLabelText("风格 A");
  await waitFor(() => expect(pickerA).toBeEnabled());
  await user.selectOptions(pickerA, "fan_ho");
  await user.selectOptions(screen.getByLabelText("风格 B"), PERSONAL_STYLE_ID);
}

describe("VisualDnaMix", () => {
  it("previews a two-style mix, shows conflicts and protections, and saves", async () => {
    const calls = installMixMock();
    const user = userEvent.setup();
    render(<VisualDnaMix />);

    await selectStyles(user);

    expect(await screen.findByRole("heading", { name: "混合预览" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /检测到 1 处风格冲突/ }),
    ).toBeInTheDocument();
    expect(screen.getByText("饱和度方向冲突")).toBeInTheDocument();
    expect(screen.getByText("保护肤色")).toBeInTheDocument();
    expect(screen.getByText(/保护约束来自两种风格的并集/)).toBeInTheDocument();

    const previewCall = calls.find((call) => call.url.endsWith("/style-mixes/preview"));
    expect(previewCall?.body).toMatchObject({
      styleA: { styleId: "fan_ho" },
      styleB: { styleId: PERSONAL_STYLE_ID },
      weight: 50,
    });

    await user.click(screen.getByRole("button", { name: /保存混合风格/ }));
    await waitFor(() =>
      expect(router.push).toHaveBeenCalledWith(`/visual-dna/${PERSONAL_STYLE_ID}`),
    );
    const saved = calls.find(
      (call) => call.method === "POST" && call.url.endsWith("/style-mixes"),
    );
    expect(saved?.body).toMatchObject({
      styleA: { styleId: "fan_ho" },
      styleB: { styleId: PERSONAL_STYLE_ID },
      name: "Fan Ho 光影几何 × 克制的城市叙事",
    });
  });

  it("re-previews when the weight changes", async () => {
    const calls = installMixMock();
    const user = userEvent.setup();
    render(<VisualDnaMix />);
    await selectStyles(user);
    await screen.findByRole("heading", { name: "混合预览" });

    const slider = screen.getByLabelText("混合权重");
    fireEvent.change(slider, { target: { value: "70" } });

    await waitFor(() => {
      const last = [...calls]
        .reverse()
        .find((call) => call.url.endsWith("/style-mixes/preview"));
      expect(last?.body).toMatchObject({ weight: 70 });
    });
  });

  it("shows a preview error and keeps the selectors", async () => {
    installMixMock({ failPreview: true });
    const user = userEvent.setup();
    render(<VisualDnaMix />);
    await selectStyles(user);

    expect(await screen.findByText("风格不存在。")).toBeInTheDocument();
    expect(screen.getByLabelText("风格 A")).toHaveValue("fan_ho");
    expect(screen.queryByRole("heading", { name: "混合预览" })).not.toBeInTheDocument();
  });
});