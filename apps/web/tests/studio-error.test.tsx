import { render, screen } from "@testing-library/react";
import axe from "axe-core";
import { describe, expect, it } from "vitest";

import { StudioError } from "@/features/generative/studio/studio-error";
import { ApiClientError } from "@/lib/api/client";

async function severeViolations(container: HTMLElement) {
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  return results.violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical",
  );
}

describe("StudioError", () => {
  it("renders the category, the plain-language message and the next step", async () => {
    const { container } = render(
      <StudioError
        error={new ApiClientError("generative_provider_rate_limited", "429", 429, {}, "req-123456")}
      />,
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Provider 错误");
    expect(alert).toHaveTextContent("Provider 触发限流，本次请求被拒绝。");
    expect(alert).toHaveTextContent(
      "下一步：稍等片刻再提交，或在 Provider 侧提高调用频率上限。",
    );
    expect(alert).toHaveTextContent("generative_provider_rate_limited · 请求 ID req-1234");
    expect(await severeViolations(container)).toHaveLength(0);
  });

  it("shows the category default guidance when the code has no tailored step", () => {
    render(<StudioError error={new ApiClientError("generative_mask_invalid", "boom", 400)} />);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "下一步：重新绘制或重新选择蒙版，确保选区落在画面内并保留足够保护区。",
    );
    expect(screen.queryByText(/请求 ID/)).not.toBeInTheDocument();
  });

  it("announces client-side guidance without the alert styling", async () => {
    const { container } = render(<StudioError error="请先选择或绘制局部编辑蒙版。" />);

    expect(screen.getByRole("status")).toHaveTextContent("请先选择或绘制局部编辑蒙版。");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(await severeViolations(container)).toHaveLength(0);
  });

  it("stays silent when there is no error to describe", () => {
    const { container } = render(<StudioError error={null} />);

    expect(container).toBeEmptyDOMElement();
  });
});
