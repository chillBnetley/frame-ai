import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EditorWorkspace } from "@/features/editor/editor-workspace";

const HEALTH = {
  status: "ok",
  service: "FRAME AI API",
  version: "0.1.0",
  storage: { ok: true, writable: true },
};

const CONFIG = {
  maxUploadBytes: 20 * 1024 * 1024,
  maxImagePixels: 40_000_000,
  allowedMimeTypes: ["image/jpeg", "image/png", "image/webp"],
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function mockHealthyApi() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/v1/health")) {
        return jsonResponse(HEALTH);
      }
      if (url.endsWith("/api/v1/config")) {
        return jsonResponse(CONFIG);
      }
      return jsonResponse({ error: { code: "not_found", message: "Not found", details: {} } }, 404);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("EditorWorkspace accessibility", () => {
  it("supports keyboard activation of the upload picker", async () => {
    mockHealthyApi();
    render(<EditorWorkspace />);

    await screen.findByText("API 已连接");
    const picker = screen.getByRole("button", { name: /拖入一张照片/ });
    const input = screen.getByTestId("file-input") as HTMLInputElement;
    const clickSpy = vi.spyOn(input, "click").mockImplementation(() => {});

    picker.focus();
    expect(picker).toHaveFocus();
    await userEvent.keyboard("{Enter}");

    expect(clickSpy).toHaveBeenCalledTimes(1);
  });

  it("has no serious or critical axe violations", async () => {
    mockHealthyApi();
    const { container } = render(<EditorWorkspace />);

    await screen.findByText("API 已连接");
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    const severe = results.violations.filter(
      (violation) => violation.impact === "serious" || violation.impact === "critical",
    );

    expect(severe).toEqual([]);
  });
});
