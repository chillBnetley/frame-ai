import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useStyles } from "@/features/photographer/hooks/use-styles";
import { styleCatalog } from "./photographer-fixtures";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useStyles", () => {
  it("loads the enabled catalog from the styles endpoint", async () => {
    const fetchMock = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(
      async () => jsonResponse({ styles: styleCatalog() }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useStyles());
    expect(result.current.loading).toBe(true);

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeNull();
    expect(result.current.styles.map((style) => style.id)).toEqual([
      "portrait",
      "clear_portrait",
      "landscape",
      "street",
      "monochrome",
      "cinematic",
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain(
      "/api/v1/ai/photographer/styles",
    );
  });

  it("surfaces a load failure and refetches on reload", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(
          { error: { code: "network", message: "unavailable", details: {} } },
          503,
        ),
      )
      .mockResolvedValueOnce(jsonResponse({ styles: styleCatalog() }));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useStyles());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.styles).toHaveLength(0);
    expect(result.current.error?.code).toBe("network");

    await act(async () => {
      result.current.reload();
    });
    await waitFor(() => expect(result.current.error).toBeNull());
    expect(result.current.loading).toBe(false);
    expect(result.current.styles).toHaveLength(6);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not request the catalog until the panel is opened", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ styles: styleCatalog() }));
    vi.stubGlobal("fetch", fetchMock);

    const { result, rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) => useStyles(enabled),
      { initialProps: { enabled: false } },
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(fetchMock).not.toHaveBeenCalled();

    rerender({ enabled: true });
    await waitFor(() => expect(result.current.styles).toHaveLength(6));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
