import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  PRIVACY_POINTS,
  PrivacyNotice,
  PrivacySummary,
} from "@/features/visual-dna/components/privacy-notice";

describe("PrivacyNotice", () => {
  it("discloses consent, extraction, retention and deletion rules", () => {
    render(<PrivacyNotice />);

    expect(
      screen.getByRole("heading", { name: "隐私与授权说明" }),
    ).toBeInTheDocument();
    for (const point of PRIVACY_POINTS) {
      expect(
        screen.getByRole("heading", { name: point.title }),
      ).toBeInTheDocument();
    }
    expect(screen.getByText(/不会用于训练任何模型/)).toBeInTheDocument();
    expect(screen.getByText(/会立即停止使用该照片/)).toBeInTheDocument();
    expect(screen.getByText(/默认为草稿，仅你可见/)).toBeInTheDocument();
  });

  it("links the summary to the full notice", () => {
    render(<PrivacySummary />);

    expect(
      screen.getByRole("link", { name: "查看完整授权说明" }),
    ).toHaveAttribute("href", "/visual-dna/privacy");
  });
});
