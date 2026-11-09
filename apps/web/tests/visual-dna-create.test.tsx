import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VisualDnaCreate } from "@/features/visual-dna/components/visual-dna-create";

import {
  PERSONAL_REFERENCE_ID,
  PERSONAL_STYLE_ID,
  imageLibrary,
  personalStyleDetail,
  personalStyleReference,
} from "./personal-style-fixtures";

const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/visual-dna/new",
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

function installCreateMock() {
  const calls: Array<{ method: string; url: string; body: unknown }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body =
        typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : init?.body;
      calls.push({ method, url, body });
      if (url.includes("/api/v1/images?limit=60") && method === "GET") {
        return jsonResponse(imageLibrary());
      }
      if (url.endsWith("/api/v1/personal-styles") && method === "POST") {
        return jsonResponse(personalStyleDetail(), 201);
      }
      if (url.endsWith(`/api/v1/personal-styles/${PERSONAL_STYLE_ID}/references`)) {
        return jsonResponse(
          {
            styleId: PERSONAL_STYLE_ID,
            references: [personalStyleReference({ id: PERSONAL_REFERENCE_ID })],
          },
          201,
        );
      }
      return jsonResponse(
        { error: { code: "not_found", message: "missing", details: {} } },
        404,
      );
    }),
  );
  return calls;
}

describe("VisualDnaCreate", () => {
  it("creates a style from library photos and starts analysis", async () => {
    const calls = installCreateMock();
    const user = userEvent.setup();
    render(<VisualDnaCreate />);

    await user.type(screen.getByLabelText("风格名称"), "克制的城市叙事");
    await user.type(
      screen.getByLabelText("一句话描述"),
      "低饱和、偏冷，但保留真实的街头质感。",
    );
    const image = await screen.findByRole("button", { name: "选择 street.png" });
    await user.click(image);
    await user.click(
      screen.getByRole("checkbox", { name: /我确认这些照片/ }),
    );
    await user.click(screen.getByRole("button", { name: /创建个人风格/ }));

    await waitFor(() =>
      expect(router.push).toHaveBeenCalledWith(
        `/visual-dna/${PERSONAL_STYLE_ID}?start=1`,
      ),
    );
    const create = calls.find(
      (call) => call.method === "POST" && call.url.endsWith("/api/v1/personal-styles"),
    );
    expect(create?.body).toMatchObject({
      name: "克制的城市叙事",
      source: "photos",
    });
    const references = calls.find((call) => call.url.endsWith("/references"));
    expect(references?.body).toMatchObject({
      consent: true,
      imageIds: ["11111111-1111-4111-8111-111111111111"],
    });
  });

  it("keeps the submit button disabled until consent is explicit", async () => {
    installCreateMock();
    const user = userEvent.setup();
    render(<VisualDnaCreate />);

    await user.type(screen.getByLabelText("风格名称"), "测试风格");
    await user.type(screen.getByLabelText("一句话描述"), "测试描述。");
    const image = await screen.findByRole("button", { name: "选择 street.png" });
    await user.click(image);

    expect(screen.getByRole("button", { name: /创建个人风格/ })).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: /我确认这些照片/ }));
    expect(screen.getByRole("button", { name: /创建个人风格/ })).toBeEnabled();
  });
});
