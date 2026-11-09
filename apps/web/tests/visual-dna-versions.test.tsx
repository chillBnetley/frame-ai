import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VisualDnaVersions } from "@/features/visual-dna/components/visual-dna-versions";

import {
  PERSONAL_STYLE_ID,
  personalStyleCompare,
  personalStyleDetail,
  personalStyleVersions,
} from "./personal-style-fixtures";

const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => `/visual-dna/${PERSONAL_STYLE_ID}/versions`,
}));

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

beforeEach(() => {
  router.push.mockReset();
});

function installVersionsMock() {
  const calls: Array<{ method: string; url: string }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      calls.push({ method, url });
      if (url.endsWith(`/api/v1/personal-styles/${PERSONAL_STYLE_ID}`) && method === "GET") {
        return jsonResponse(personalStyleDetail());
      }
      if (url.endsWith(`/api/v1/personal-styles/${PERSONAL_STYLE_ID}/versions`)) {
        return jsonResponse(personalStyleVersions());
      }
      if (url.includes(`/api/v1/personal-styles/${PERSONAL_STYLE_ID}/compare`)) {
        return jsonResponse(personalStyleCompare());
      }
      if (url.endsWith("/versions/1.0/restore") && method === "POST") {
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

describe("VisualDnaVersions", () => {
  it("lists versions and compares the two selected versions", async () => {
    installVersionsMock();
    render(<VisualDnaVersions styleId={PERSONAL_STYLE_ID} />);

    expect((await screen.findAllByText("v1.1")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("v1.0").length).toBeGreaterThan(0);
    expect(screen.getByText("参考照片融合")).toBeInTheDocument();
    expect(await screen.findByText("profile.name")).toBeInTheDocument();
    expect(screen.getByText("克制的城市叙事")).toBeInTheDocument();
    expect(screen.getByText("城市")).toBeInTheDocument();
  });

  it("restores an older version after confirmation", async () => {
    const calls = installVersionsMock();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    render(<VisualDnaVersions styleId={PERSONAL_STYLE_ID} />);

    await screen.findAllByText("v1.0");
    const restoreButtons = screen.getAllByRole("button", { name: "恢复为新版本" });
    await user.click(restoreButtons[restoreButtons.length - 1]);

    await waitFor(() =>
      expect(
        calls.some(
          (call) =>
            call.method === "POST" && call.url.endsWith("/versions/1.0/restore"),
        ),
      ).toBe(true),
    );
    expect(router.push).toHaveBeenCalledWith(`/visual-dna/${PERSONAL_STYLE_ID}`);
  });
});
