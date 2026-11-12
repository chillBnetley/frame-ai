import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const pathnameState = vi.hoisted(() => ({ current: "/" }));

vi.mock("next/navigation", () => ({
  usePathname: () => pathnameState.current,
}));

vi.mock("next/image", () => ({
  default: ({ src, alt }: { src: string; alt: string }) => (
    // eslint-disable-next-line @next/next/no-img-element -- test double for next/image
    <img src={src} alt={alt} />
  ),
}));

import { SiteHeader } from "@/components/site-header";

function renderHeader(pathname: string) {
  pathnameState.current = pathname;
  render(<SiteHeader />);
  return screen.getByRole("navigation", { name: "主导航" });
}

describe("SiteHeader navigation", () => {
  it("marks the photo workbench only on the root route", () => {
    const nav = renderHeader("/");

    expect(within(nav).getByRole("link", { name: "照片工作台" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "Visual DNA" })).not.toHaveAttribute(
      "aria-current",
    );
    expect(within(nav).getByRole("link", { name: "Master Vision" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("marks Visual DNA on its nested routes", () => {
    const nav = renderHeader("/visual-dna/new");

    const active = within(nav).getByRole("link", { name: "Visual DNA" });
    expect(active).toHaveAttribute("aria-current", "page");
    expect(active).toHaveClass("text-[#1f6a5a]");
    expect(within(nav).getByRole("link", { name: "照片工作台" })).not.toHaveAttribute(
      "aria-current",
    );
    expect(within(nav).getByRole("link", { name: "Master Vision" })).not.toHaveAttribute(
      "aria-current",
    );

    const mobile = screen
      .getAllByRole("link", { name: "Visual DNA" })
      .find((link) => !nav.contains(link));
    expect(mobile).toHaveAttribute("aria-current", "page");
  });

  it("marks Master Vision on its nested routes", () => {
    const nav = renderHeader("/master-vision/workspace");

    expect(within(nav).getByRole("link", { name: "Master Vision" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "照片工作台" })).not.toHaveAttribute(
      "aria-current",
    );
    expect(within(nav).getByRole("link", { name: "Visual DNA" })).not.toHaveAttribute(
      "aria-current",
    );
  });
});
