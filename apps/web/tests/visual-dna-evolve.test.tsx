import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VisualDnaEvolve } from "@/features/visual-dna/components/visual-dna-evolve";
import type {
  StyleEvolutionRecord,
  StyleFeedbackRecord,
} from "@/types/style-evolution";

import {
  PERSONAL_STYLE_ID,
  STYLE_EVOLUTION_ID,
  personalStyleDetail,
  styleEvolutionPreview,
  styleFeedbackRecord,
} from "./personal-style-fixtures";

const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => `/visual-dna/${PERSONAL_STYLE_ID}/evolve`,
}));

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function noContent(): Response {
  return new Response(null, { status: 204 });
}

interface Call {
  method: string;
  url: string;
  body: unknown;
}

function installEvolutionMock(
  options: {
    feedbacks?: StyleFeedbackRecord[];
    evolutions?: StyleEvolutionRecord[];
  } = {},
) {
  const calls: Call[] = [];
  const feedbacks = [...(options.feedbacks ?? [])];
  const evolutions = [...(options.evolutions ?? [])];
  const base = `/api/v1/personal-styles/${PERSONAL_STYLE_ID}`;

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const body =
        typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : init?.body;
      calls.push({ method, url, body });

      if (url === base && method === "GET") {
        return jsonResponse(personalStyleDetail());
      }
      if (url.endsWith("/evolutions") && method === "GET") {
        return jsonResponse({ styleId: PERSONAL_STYLE_ID, evolutions });
      }
      if (url.endsWith("/evolve/preview") && method === "POST") {
        return jsonResponse(styleEvolutionPreview());
      }
      if (url.endsWith(`/evolve/${STYLE_EVOLUTION_ID}/apply`) && method === "POST") {
        return jsonResponse(personalStyleDetail());
      }
      if (url.endsWith(`/evolve/${STYLE_EVOLUTION_ID}/discard`) && method === "POST") {
        return noContent();
      }
      if (url.includes("/feedback/") && method === "DELETE") {
        return noContent();
      }
      if (url.endsWith("/feedback")) {
        if (method === "GET") {
          return jsonResponse({ styleId: PERSONAL_STYLE_ID, feedbacks });
        }
        if (method === "POST") {
          const payload = body as {
            feedbackType: StyleFeedbackRecord["feedbackType"];
            scope: StyleFeedbackRecord["scope"];
            note?: string;
          };
          const record = styleFeedbackRecord({
            feedbackType: payload.feedbackType,
            scope: payload.scope,
            note: payload.note ?? null,
          });
          feedbacks.push(record);
          return jsonResponse(record, 201);
        }
      }
      return jsonResponse(
        { error: { code: "not_found", message: "missing", details: {} } },
        404,
      );
    }),
  );
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

beforeEach(() => {
  router.push.mockReset();
});

describe("VisualDnaEvolve", () => {
  it("records profile feedback, previews a bounded candidate, and applies it", async () => {
    const calls = installEvolutionMock();
    const user = userEvent.setup();
    render(<VisualDnaEvolve styleId={PERSONAL_STYLE_ID} />);

    expect(
      await screen.findByRole("heading", { name: /反馈演变/ }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "色彩太浓" }));
    await user.click(screen.getByRole("button", { name: "加入个人风格" }));
    await user.click(screen.getByRole("button", { name: "记录反馈" }));

    expect(
      await screen.findByText(/已作为个人风格反馈记录/),
    ).toBeInTheDocument();
    const record = calls.find(
      (call) => call.method === "POST" && call.url.endsWith("/feedback"),
    );
    expect(record?.body).toEqual({
      feedbackType: "color_too_strong",
      scope: "profile",
    });

    await user.click(screen.getByRole("button", { name: "生成演变候选" }));
    expect(await screen.findByText("饱和度")).toBeInTheDocument();
    expect(screen.getByText(/基于 1 条反馈/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "确认并应用为新版本" }));
    await waitFor(() =>
      expect(router.push).toHaveBeenCalledWith(`/visual-dna/${PERSONAL_STYLE_ID}`),
    );
    const apply = calls.find((call) => call.url.endsWith("/apply"));
    expect(apply?.body).toMatchObject({ confirm: true });
  });

  it("keeps single-edit feedback from enabling a profile evolution", async () => {
    installEvolutionMock();
    const user = userEvent.setup();
    render(<VisualDnaEvolve styleId={PERSONAL_STYLE_ID} />);

    await screen.findByRole("heading", { name: /反馈演变/ });
    expect(screen.getByRole("button", { name: "生成演变候选" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "记录反馈" }));
    expect(
      await screen.findByText(/已记录本次调整反馈/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "生成演变候选" })).toBeDisabled();
  });

  it("discards a proposed candidate without applying it", async () => {
    const calls = installEvolutionMock({ feedbacks: [styleFeedbackRecord()] });
    const user = userEvent.setup();
    render(<VisualDnaEvolve styleId={PERSONAL_STYLE_ID} />);

    await screen.findByRole("heading", { name: /反馈演变/ });
    await user.click(screen.getByRole("button", { name: "生成演变候选" }));
    expect(await screen.findByText("饱和度")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "放弃候选" }));
    expect(await screen.findByText(/已放弃该候选/)).toBeInTheDocument();
    expect(screen.queryByText("饱和度")).not.toBeInTheDocument();
    expect(
      calls.find((call) => call.url.endsWith("/discard"))?.method,
    ).toBe("POST");
  });
});
