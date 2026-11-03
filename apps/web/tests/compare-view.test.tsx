import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CompareView } from "@/features/editor/components/compare-view";
import { REVISION_ID, SESSION_ID } from "./session-fixtures";

const COMPARE = {
  original: { previewUrl: "/api/v1/previews/original", width: 800, height: 600 },
  revision: { previewUrl: "/api/v1/previews/edited", width: 800, height: 600 },
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function mockCompare(response = jsonResponse(COMPARE)) {
  const fetchMock = vi.fn<typeof fetch>(async () => response.clone());
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderView(overrides: Partial<Parameters<typeof CompareView>[0]> = {}) {
  const onClose = vi.fn();
  render(
    <CompareView
      sessionId={SESSION_ID}
      revisionId={REVISION_ID}
      dirty={false}
      onClose={onClose}
      {...overrides}
    />,
  );
  return { onClose };
}

describe("CompareView", () => {
  it("loads matched-size original and edited previews", async () => {
    const fetchMock = mockCompare();
    renderView();

    expect(await screen.findByAltText("原图")).toHaveAttribute(
      "src",
      COMPARE.original.previewUrl,
    );
    expect(screen.getByAltText("编辑后的版本")).toHaveAttribute(
      "src",
      COMPARE.revision.previewUrl,
    );
    expect(screen.getByText("800 × 600")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toContain(
      `/api/v1/sessions/${SESSION_ID}/compare?revisionId=${REVISION_ID}`,
    );
  });

  it("moves the split line", async () => {
    mockCompare();
    renderView();

    const original = await screen.findByAltText("原图");
    expect(original).toHaveStyle({ clipPath: "inset(0 50% 0 0)" });

    fireEvent.change(screen.getByRole("slider", { name: "对比分割线位置" }), {
      target: { value: "70" },
    });
    expect(original).toHaveStyle({ clipPath: "inset(0 30% 0 0)" });
  });

  it("shows the original while the hold button is pressed", async () => {
    mockCompare();
    renderView();
    await screen.findByAltText("原图");

    const hold = screen.getByRole("button", { name: "按住查看原图" });
    fireEvent.pointerDown(hold);
    expect(screen.getByText("正在查看原图")).toBeInTheDocument();
    expect(screen.queryByAltText("编辑后的版本")).not.toBeInTheDocument();
    expect(screen.getByAltText("原图")).toBeInTheDocument();

    fireEvent.pointerUp(hold);
    expect(screen.getByAltText("编辑后的版本")).toBeInTheDocument();
  });

  it("supports holding the compare key with the keyboard", async () => {
    mockCompare();
    renderView();
    await screen.findByAltText("原图");

    const hold = screen.getByRole("button", { name: "按住查看原图" });
    fireEvent.keyDown(hold, { key: " " });
    expect(screen.getByAltText("原图")).toBeInTheDocument();
    expect(screen.queryByAltText("编辑后的版本")).not.toBeInTheDocument();

    fireEvent.keyUp(hold, { key: " " });
    expect(screen.getByAltText("编辑后的版本")).toBeInTheDocument();
  });

  it("notes that compare uses the saved revision while dirty", async () => {
    mockCompare();
    renderView({ dirty: true });
    await screen.findByAltText("原图");

    expect(screen.getByText(/对比基于已保存版本/)).toBeInTheDocument();
  });

  it("falls back to contain when the two sides have different aspect ratios", async () => {
    mockCompare(
      jsonResponse({
        original: { previewUrl: "/api/v1/previews/original", width: 800, height: 600 },
        revision: { previewUrl: "/api/v1/previews/edited", width: 400, height: 800 },
      }),
    );
    renderView();

    const original = await screen.findByAltText("原图");
    expect(original).toHaveClass("object-contain");
    expect(screen.getByAltText("编辑后的版本")).toHaveClass("object-contain");
    expect(screen.getByText(/比例不同/)).toBeInTheDocument();
  });

  it("shows a readable error and retries", async () => {
    const fetchMock = mockCompare(
      jsonResponse({ error: { code: "internal_error", message: "boom", details: {} } }, 500),
    );
    renderView();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "服务出现未预期错误，请稍后重试。",
    );

    await userEvent.click(screen.getByRole("button", { name: "重新加载对比图" }));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("closes the compare view", async () => {
    mockCompare();
    const { onClose } = renderView();
    await screen.findByAltText("原图");

    await userEvent.click(screen.getByRole("button", { name: "退出对比" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
