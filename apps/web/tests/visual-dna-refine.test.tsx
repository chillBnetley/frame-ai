import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VisualDnaRefine } from "@/features/visual-dna/components/visual-dna-refine";

import {
  PERSONAL_STYLE_ID,
  customRefineResponse,
  personalStyleDetail,
} from "./personal-style-fixtures";

const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => `/visual-dna/${PERSONAL_STYLE_ID}/refine`,
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

function installRefineMock() {
  const calls: Array<{ method: string; url: string; body: unknown }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body =
        typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : init?.body;
      calls.push({ method, url, body });
      if (url.endsWith(`/api/v1/personal-styles/${PERSONAL_STYLE_ID}`) && method === "GET") {
        return jsonResponse(personalStyleDetail());
      }
      if (url.endsWith(`/api/v1/personal-styles/${PERSONAL_STYLE_ID}/refine`)) {
        return jsonResponse(customRefineResponse());
      }
      if (url.endsWith(`/api/v1/personal-styles/${PERSONAL_STYLE_ID}/refine/apply`)) {
        return jsonResponse(personalStyleDetail());
      }
      return jsonResponse(
        { error: { code: "not_found", message: "missing", details: {} } },
        404,
      );
    }),
  );
  return calls;
}

describe("VisualDnaRefine", () => {
  it("previews field changes and applies them as a new version", async () => {
    const calls = installRefineMock();
    const user = userEvent.setup();
    render(<VisualDnaRefine styleId={PERSONAL_STYLE_ID} />);

    expect(
      await screen.findByRole("heading", { name: /继续调整「克制的城市叙事」/ }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "保留更多高光" }));
    await user.click(screen.getByRole("button", { name: "解析修改" }));

    expect(await screen.findByText("修改预览")).toBeInTheDocument();
    expect(screen.getByText("高光表现")).toBeInTheDocument();
    expect(screen.getByText("保留更多高光细节")).toBeInTheDocument();
    expect(screen.getByText("暗部表现")).toBeInTheDocument();
    expect(screen.getByText("保留更多暗部层次")).toBeInTheDocument();
    expect(screen.getByText("饱和度目标")).toBeInTheDocument();
    expect(screen.getAllByText(/当前 v1.0/).length).toBeGreaterThan(0);

    const refine = calls.find((call) => call.url.endsWith("/refine"));
    expect(refine?.body).toEqual({ instruction: "保留更多高光" });

    await user.click(screen.getByRole("button", { name: "应用为新版本" }));
    await waitFor(() =>
      expect(router.push).toHaveBeenCalledWith(`/visual-dna/${PERSONAL_STYLE_ID}`),
    );
    const apply = calls.find((call) => call.url.endsWith("/refine/apply"));
    expect(apply?.body).toMatchObject({
      note: "保留更多高光",
      draft: { targets: { highlights: -4, shadows: 4 } },
    });
  });

  it("clears a stale preview when the instruction changes", async () => {
    installRefineMock();
    const user = userEvent.setup();
    render(<VisualDnaRefine styleId={PERSONAL_STYLE_ID} />);

    await screen.findByRole("heading", { name: /继续调整/ });
    const textarea = screen.getByPlaceholderText(/更克制一点/);
    await user.type(textarea, "保留更多高光");
    await user.click(screen.getByRole("button", { name: "解析修改" }));
    await screen.findByText("修改预览");

    await user.type(textarea, "，暗部不要太黑");
    expect(screen.queryByText("修改预览")).not.toBeInTheDocument();
  });
});
