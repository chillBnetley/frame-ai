import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { StyleLibraryPage } from "@/features/master-vision/components/style-library-page";
import { MasterVisionCompare } from "@/features/master-vision/components/workspace/compare-stage";
import { StyleDetailView } from "@/features/master-vision/components/style-detail-view";

import { GENRE_ITEM, styleDetail, styleItem } from "./master-vision-fixtures";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("StyleLibraryPage", () => {
  it("lists styles, filters by search, and toggles a favorite", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        calls.push(`${init?.method ?? "GET"} ${url}`);
        if (url.includes("/favorite")) {
          return jsonResponse({ styleId: "fan_ho", favorite: true });
        }
        return jsonResponse({
          styles: [styleItem(), { ...GENRE_ITEM, kind: "master", name: "环境人像档案" }],
        });
      }),
    );
    const user = userEvent.setup();
    render(<StyleLibraryPage kind="master" />);

    await screen.findByRole("heading", { name: "Fan Ho 光影几何" });
    expect(calls[0]).toContain("kind=master");

    await user.type(screen.getByRole("searchbox", { name: "搜索风格" }), "Fan");
    await waitFor(() => expect(calls.some((call) => call.includes("search=Fan"))).toBe(true));

    await user.click(screen.getByRole("button", { name: "收藏 Fan Ho 光影几何" }));
    await waitFor(() =>
      expect(calls.some((call) => call.startsWith("POST") && call.includes("/favorite"))).toBe(
        true,
      ),
    );
  });

  it("shows an empty state and a retry state", async () => {
    let fail = true;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        if (fail) {
          fail = false;
          return jsonResponse(
            { error: { code: "server_busy", message: "busy", details: {} } },
            503,
          );
        }
        return jsonResponse({ styles: [] });
      }),
    );
    const user = userEvent.setup();
    render(<StyleLibraryPage kind="genre" />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/风格库加载失败/);
    await user.click(screen.getByRole("button", { name: "重新加载" }));
    expect(await screen.findByText("没有匹配的风格")).toBeInTheDocument();
  });
});

describe("StyleDetailView", () => {
  it("renders the full archive and starts creation with the style preselected", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(styleDetail())),
    );
    const user = userEvent.setup();
    render(<StyleDetailView styleId="fan_ho" />);

    expect(await screen.findByRole("heading", { name: "Fan Ho 光影几何" })).toBeInTheDocument();
    expect(screen.getByText(/光是主角/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "视觉语言如何形成画面" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "适合的场景" })).toBeInTheDocument();
    expect(screen.getByText("不适用的场景")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /开始创作/ })).toHaveAttribute(
      "href",
      "/master-vision/workspace?style=fan_ho",
    );

    await user.click(screen.getByRole("button", { name: "收藏风格" }));
    expect(await screen.findByRole("button", { name: "已收藏" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});

describe("MasterVisionCompare", () => {
  it("switches between split, original, result, and zoom", async () => {
    const user = userEvent.setup();
    render(
      <MasterVisionCompare
        originalUrl="/original.jpg"
        resultUrl="/result.jpg"
        loading={false}
        error={null}
      />,
    );

    expect(screen.getByAltText("原图")).toBeInTheDocument();
    expect(screen.getByAltText("风格处理结果")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "查看原图" }));
    expect(screen.queryByAltText("风格处理结果")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "查看结果" }));
    expect(screen.queryByAltText("原图")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "放大查看" }));
    expect(screen.getByRole("dialog", { name: "放大查看处理结果" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows upload, render failure, and retry states", async () => {
    const onRetry = vi.fn();
    const { rerender } = render(
      <MasterVisionCompare
        originalUrl={null}
        resultUrl={null}
        loading={false}
        error={null}
      />,
    );
    expect(screen.getByText("先上传一张照片")).toBeInTheDocument();

    rerender(
      <MasterVisionCompare
        originalUrl="/original.jpg"
        resultUrl={null}
        loading={false}
        error="渲染失败"
        onRetry={onRetry}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("渲染失败");
    await userEvent.click(screen.getByRole("button", { name: "重试渲染" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
