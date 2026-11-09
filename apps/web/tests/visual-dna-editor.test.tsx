import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VisualDnaEditor } from "@/features/visual-dna/components/visual-dna-editor";

import { PERSONAL_STYLE_ID, personalStyleDetail } from "./personal-style-fixtures";

const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => `/visual-dna/${PERSONAL_STYLE_ID}/edit`,
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

function installEditorMock() {
  const calls: Array<{ method: string; body: unknown }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body =
        typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : init?.body;
      calls.push({ method, body });
      if (method === "GET" && url.endsWith(`/api/v1/personal-styles/${PERSONAL_STYLE_ID}`)) {
        return jsonResponse(personalStyleDetail());
      }
      if (method === "PATCH" && url.endsWith(`/api/v1/personal-styles/${PERSONAL_STYLE_ID}`)) {
        const detail = personalStyleDetail();
        if (body && typeof body === "object" && "name" in body) {
          detail.style = { ...detail.style, name: String((body as { name: string }).name) };
        }
        return jsonResponse(detail);
      }
      return jsonResponse(
        { error: { code: "not_found", message: "missing", details: {} } },
        404,
      );
    }),
  );
  return calls;
}

describe("VisualDnaEditor", () => {
  it("saves only changed fields and explains user-confirmed protection", async () => {
    const calls = installEditorMock();
    const user = userEvent.setup();
    render(<VisualDnaEditor styleId={PERSONAL_STYLE_ID} />);

    await screen.findByRole("heading", { name: /编辑「克制的城市叙事」/ });
    expect(screen.getByText(/不会被静默覆盖/)).toBeInTheDocument();

    const name = screen.getByLabelText("风格名称");
    await user.clear(name);
    await user.type(name, "克制的城市 II");
    await user.click(screen.getByRole("button", { name: "保存为新版本" }));

    await waitFor(() => expect(router.push).toHaveBeenCalledWith(`/visual-dna/${PERSONAL_STYLE_ID}`));
    const patch = calls.find((call) => call.method === "PATCH");
    expect(patch?.body).toEqual({ name: "克制的城市 II" });
  });

  it("sends target sliders as a bounded target map", async () => {
    const calls = installEditorMock();
    const user = userEvent.setup();
    render(<VisualDnaEditor styleId={PERSONAL_STYLE_ID} />);

    await screen.findByRole("heading", { name: /编辑「克制的城市叙事」/ });
    const slider = screen.getByRole("slider", { name: "饱和度" });
    fireEvent.change(slider, { target: { value: "-20" } });
    await user.click(screen.getByRole("button", { name: "保存为新版本" }));

    await waitFor(() => expect(router.push).toHaveBeenCalled());
    const patch = calls.find((call) => call.method === "PATCH");
    expect(patch?.body).toMatchObject({
      targets: {
        saturation: -20,
        temperature: -6,
        contrast: -4,
      },
    });
  });

  it("saves edited trait text as a user override", async () => {
    const calls = installEditorMock();
    const user = userEvent.setup();
    render(<VisualDnaEditor styleId={PERSONAL_STYLE_ID} />);

    await screen.findByRole("heading", { name: /编辑「克制的城市叙事」/ });
    const expression = screen.getByLabelText("光线表达");
    await user.clear(expression);
    await user.type(expression, "自然侧光，重视暗部与高光关系。");
    await user.click(screen.getByRole("button", { name: "保存为新版本" }));

    await waitFor(() => expect(router.push).toHaveBeenCalled());
    const patch = calls.find((call) => call.method === "PATCH");
    expect(patch?.body).toMatchObject({
      traits: { lightExpression: "自然侧光，重视暗部与高光关系。" },
    });
  });

  it("resets unsaved changes", async () => {
    installEditorMock();
    const user = userEvent.setup();
    render(<VisualDnaEditor styleId={PERSONAL_STYLE_ID} />);

    await screen.findByRole("heading", { name: /编辑「克制的城市叙事」/ });
    const name = screen.getByLabelText("风格名称");
    await user.clear(name);
    await user.type(name, "临时名字");
    expect(screen.getByRole("button", { name: "撤销未保存修改" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "撤销未保存修改" }));
    expect(name).toHaveValue("克制的城市叙事");
    expect(screen.getByRole("button", { name: "撤销未保存修改" })).toBeDisabled();
  });
});
