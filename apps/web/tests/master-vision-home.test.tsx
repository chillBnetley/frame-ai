import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MasterVisionHome } from "@/features/master-vision/components/master-vision-home";

import { GENRE_ITEM, styleItem } from "./master-vision-fixtures";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function installHomeMock(options: { failOnce?: boolean } = {}) {
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
      if (url.includes("/api/v1/styles/recommended")) {
        return jsonResponse({
          basis: "library",
          scene: null,
          styles: [{ style: styleItem(), reason: "适合作为风格起点。" }],
        });
      }
      if (url.includes("/api/v1/styles/recent")) {
        return jsonResponse({
          styles: [
            {
              style: { ...GENRE_ITEM, favorite: false },
              lastUsedAt: "2026-11-08T00:00:00Z",
            },
          ],
        });
      }
      if (url.includes("/api/v1/styles/favorites")) {
        return jsonResponse({ styles: [] });
      }
      if (url.includes("/favorite")) {
        return jsonResponse({ styleId: "fan_ho", favorite: true });
      }
      return jsonResponse({ error: { code: "not_found", message: "missing", details: {} } }, 404);
    }),
  );
  return calls;
}

describe("MasterVisionHome", () => {
  it("shows recommended, recent, and empty favorite states", async () => {
    installHomeMock();
    render(<MasterVisionHome />);

    expect(screen.getByRole("heading", { name: /把大师的视觉语言/ })).toBeInTheDocument();
    await screen.findByRole("heading", { name: "Fan Ho 光影几何" });
    expect(screen.getByRole("heading", { name: "环境人像" })).toBeInTheDocument();
    expect(screen.getByText("还没有收藏")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /进入大师风格库/ })).toHaveAttribute(
      "href",
      "/master-vision/masters",
    );
  });

  it("favorites a style optimistically and calls the API", async () => {
    const calls = installHomeMock();
    const user = userEvent.setup();
    render(<MasterVisionHome />);

    const button = await screen.findByRole("button", { name: "收藏 Fan Ho 光影几何" });
    await user.click(button);

    await waitFor(() =>
      expect(
        calls.some((call) => call.startsWith("POST") && call.includes("/styles/fan_ho/favorite")),
      ).toBe(true),
    );
    const pressed = await screen.findAllByRole("button", {
      name: "取消收藏 Fan Ho 光影几何",
    });
    expect(pressed.length).toBeGreaterThanOrEqual(1);
    expect(pressed.every((item) => item.getAttribute("aria-pressed") === "true")).toBe(true);
  });

  it("shows a retry state when the library cannot be reached", async () => {
    installHomeMock({ failOnce: true });
    const user = userEvent.setup();
    render(<MasterVisionHome />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/无法连接/);
    await user.click(screen.getByRole("button", { name: "重新加载" }));
    await screen.findByRole("heading", { name: "Fan Ho 光影几何" });
  });
});
