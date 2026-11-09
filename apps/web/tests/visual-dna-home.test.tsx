import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { VisualDnaHome } from "@/features/visual-dna/components/visual-dna-home";

import { personalStyleItem } from "./personal-style-fixtures";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function installHomeMock(options: { empty?: boolean; failOnce?: boolean } = {}) {
  const calls: string[] = [];
  let failed = false;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push(`${init?.method ?? "GET"} ${url}`);
      if (options.failOnce && !failed) {
        failed = true;
        throw new Error("offline");
      }
      if (url.includes("/api/v1/personal-styles") && !url.includes("/favorite")) {
        return jsonResponse({ styles: options.empty ? [] : [personalStyleItem()] });
      }
      if (url.includes("/favorite")) {
        return jsonResponse({ styleId: personalStyleItem().id, favorite: true });
      }
      return jsonResponse(
        { error: { code: "not_found", message: "missing", details: {} } },
        404,
      );
    }),
  );
  return calls;
}

describe("VisualDnaHome", () => {
  it("shows the personal style list and privacy copy", async () => {
    installHomeMock();
    render(<VisualDnaHome />);

    expect(
      screen.getByRole("heading", { name: /从你自己的照片里/ }),
    ).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "克制的城市叙事" })).toBeInTheDocument();
    expect(screen.getByText("参考照片")).toBeInTheDocument();
    expect(screen.getByText(/不用于模型训练/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /从参考照片创建/ })).toHaveAttribute(
      "href",
      "/visual-dna/new",
    );
  });

  it("shows an empty state with a creation link", async () => {
    installHomeMock({ empty: true });
    render(<VisualDnaHome />);

    expect(await screen.findByText("还没有个人风格")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /创建第一个个人风格/ })).toHaveAttribute(
      "href",
      "/visual-dna/new",
    );
  });

  it("favorites a personal style optimistically", async () => {
    const calls = installHomeMock();
    const user = userEvent.setup();
    render(<VisualDnaHome />);

    const button = await screen.findByRole("button", {
      name: "收藏 克制的城市叙事",
    });
    await user.click(button);

    await waitFor(() =>
      expect(
        calls.some((call) => call.startsWith("POST") && call.includes("/favorite")),
      ).toBe(true),
    );
    expect(
      await screen.findByRole("button", { name: "取消收藏 克制的城市叙事" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("offers a retry when the style list cannot be reached", async () => {
    installHomeMock({ failOnce: true });
    const user = userEvent.setup();
    render(<VisualDnaHome />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/无法连接/);
    await user.click(screen.getByRole("button", { name: "重新加载" }));
    await screen.findByRole("heading", { name: "克制的城市叙事" });
  });
});
