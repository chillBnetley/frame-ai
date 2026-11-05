import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PreviewImage } from "@/features/editor/components/preview-image";
import type { PreviewState } from "@/features/editor/state/editor-reducer";

const ALT = "编辑后的预览";

function previewState(overrides: Partial<PreviewState> = {}): PreviewState {
  return {
    url: "/previews/base",
    width: 800,
    height: 600,
    quality: "draft",
    status: "ready",
    seq: 1,
    version: 1,
    error: null,
    warnings: [],
    ...overrides,
  };
}

function stagingImage(container: HTMLElement): HTMLImageElement | null {
  return container.querySelector('img[aria-hidden="true"]');
}

function activeImage(): HTMLImageElement {
  return screen.getByAltText(ALT) as HTMLImageElement;
}

function loadInitialImage(): void {
  fireEvent.load(activeImage());
}

const originalDecode = Object.getOwnPropertyDescriptor(
  HTMLImageElement.prototype,
  "decode",
);

function stubDecode(implementation: () => Promise<void>): void {
  Object.defineProperty(HTMLImageElement.prototype, "decode", {
    configurable: true,
    writable: true,
    value: vi.fn(implementation),
  });
}

afterEach(() => {
  if (originalDecode) {
    Object.defineProperty(HTMLImageElement.prototype, "decode", originalDecode);
  } else {
    delete (HTMLImageElement.prototype as { decode?: unknown }).decode;
  }
});

describe("PreviewImage", () => {
  it("keeps the active image mounted while the next preview preloads", () => {
    const { container, rerender } = render(
      <PreviewImage preview={previewState()} alt={ALT} />,
    );
    loadInitialImage();

    rerender(
      <PreviewImage
        preview={previewState({ url: "/previews/next", status: "loading", seq: 2 })}
        alt={ALT}
      />,
    );

    expect(activeImage()).toHaveAttribute("src", "/previews/base");
    expect(stagingImage(container)).toHaveAttribute("src", "/previews/next");
  });

  it("swaps to the new image only after it has loaded", () => {
    const { container, rerender } = render(
      <PreviewImage preview={previewState()} alt={ALT} />,
    );
    loadInitialImage();

    rerender(
      <PreviewImage
        preview={previewState({ url: "/previews/next", status: "loading", seq: 2 })}
        alt={ALT}
      />,
    );

    fireEvent.load(stagingImage(container)!);

    expect(activeImage()).toHaveAttribute("src", "/previews/next");
    expect(stagingImage(container)).toBeNull();
  });

  it("ignores a preload that resolves after a newer preview arrives", async () => {
    const decodes: Array<() => void> = [];
    stubDecode(
      () =>
        new Promise<void>((resolve) => {
          decodes.push(resolve);
        }),
    );

    const { container, rerender } = render(
      <PreviewImage preview={previewState()} alt={ALT} />,
    );
    loadInitialImage();
    rerender(
      <PreviewImage
        preview={previewState({ url: "/previews/intermediate", status: "loading", seq: 2 })}
        alt={ALT}
      />,
    );
    fireEvent.load(stagingImage(container)!);

    rerender(
      <PreviewImage
        preview={previewState({ url: "/previews/latest", status: "loading", seq: 3 })}
        alt={ALT}
      />,
    );
    await act(async () => {
      decodes[0]?.();
      await Promise.resolve();
    });

    expect(activeImage()).toHaveAttribute("src", "/previews/base");
    const latestStaging = stagingImage(container);
    expect(latestStaging).toHaveAttribute("src", "/previews/latest");

    await act(async () => {
      fireEvent.load(latestStaging!);
      decodes[1]?.();
      await Promise.resolve();
    });
    expect(activeImage()).toHaveAttribute("src", "/previews/latest");
  });

  it("keeps the old image and shows a notice when the new preview fails", () => {
    const onError = vi.fn();
    const { container, rerender } = render(
      <PreviewImage preview={previewState()} alt={ALT} onError={onError} />,
    );
    loadInitialImage();

    rerender(
      <PreviewImage
        preview={previewState({ url: "/previews/broken", status: "loading", seq: 2 })}
        alt={ALT}
        onError={onError}
      />,
    );
    fireEvent.error(stagingImage(container)!);

    expect(activeImage()).toHaveAttribute("src", "/previews/base");
    expect(onError).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent(
      "新预览加载失败，仍显示上一版本",
    );
    expect(stagingImage(container)).toBeNull();
  });

  it("requests at most one retry when the very first preview fails", () => {
    const onError = vi.fn();
    const { rerender } = render(
      <PreviewImage
        preview={previewState({ url: null, status: "idle", seq: 0 })}
        alt={ALT}
        onError={onError}
      />,
    );

    rerender(
      <PreviewImage
        preview={previewState({ url: "/previews/first", status: "loading", seq: 1 })}
        alt={ALT}
        onError={onError}
      />,
    );
    fireEvent.error(activeImage());
    expect(onError).toHaveBeenCalledTimes(1);

    rerender(
      <PreviewImage
        preview={previewState({ url: "/previews/first", status: "loading", seq: 2 })}
        alt={ALT}
        onError={onError}
      />,
    );
    fireEvent.error(activeImage());

    expect(onError).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("renders a generating placeholder when no preview exists yet", () => {
    render(
      <PreviewImage
        preview={previewState({ url: null, status: "idle", seq: 0 })}
        alt={ALT}
      />,
    );

    expect(screen.queryByAltText(ALT)).not.toBeInTheDocument();
    expect(screen.getByText("正在生成预览…")).toBeInTheDocument();
  });
});
