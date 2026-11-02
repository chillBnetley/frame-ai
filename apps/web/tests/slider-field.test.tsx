import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SliderField } from "@/features/editor/components/slider-field";

function renderField(overrides: Partial<Parameters<typeof SliderField>[0]> = {}) {
  const onChange = vi.fn();
  const onCommit = vi.fn();
  render(
    <SliderField
      label="曝光"
      value={0}
      min={-3}
      max={3}
      step={0.01}
      defaultValue={0}
      unit="EV"
      onChange={onChange}
      onCommit={onCommit}
      {...overrides}
    />,
  );
  return { onChange, onCommit };
}

describe("SliderField", () => {
  it("exposes range, step, and a unit-aware aria-valuetext", () => {
    renderField({ value: 0.5 });

    const slider = screen.getByRole("slider", { name: "曝光" });
    expect(slider).toHaveAttribute("min", "-3");
    expect(slider).toHaveAttribute("max", "3");
    expect(slider).toHaveAttribute("step", "0.01");
    expect(slider).toHaveAttribute("aria-valuetext", "+0.50 EV");

    const number = screen.getByRole("spinbutton", { name: "曝光" });
    expect(number).toHaveAttribute("step", "0.01");
    expect(number).toHaveValue(0.5);
  });

  it("rounds slider changes to two decimals and commits on release", () => {
    const { onChange, onCommit } = renderField();
    const slider = screen.getByRole("slider", { name: "曝光" });

    fireEvent.change(slider, { target: { value: "1.234" } });
    expect(onChange).toHaveBeenLastCalledWith(1.23);

    fireEvent.pointerUp(slider);
    expect(onCommit).toHaveBeenCalledTimes(1);
  });

  it("clamps out-of-range values and restores the default on double click", () => {
    const { onChange, onCommit } = renderField({ value: 1 });

    fireEvent.change(screen.getByRole("slider", { name: "曝光" }), {
      target: { value: "9" },
    });
    expect(onChange).toHaveBeenLastCalledWith(3);

    fireEvent.doubleClick(screen.getByRole("slider", { name: "曝光" }));
    expect(onChange).toHaveBeenLastCalledWith(0);
    expect(onCommit).toHaveBeenCalled();
  });

  it("normalizes numeric input and commits on Enter", () => {
    const { onChange, onCommit } = renderField();
    const number = screen.getByRole("spinbutton", { name: "曝光" });

    fireEvent.change(number, { target: { value: "0.333" } });
    expect(onChange).toHaveBeenLastCalledWith(0.33);

    fireEvent.keyDown(number, { key: "Enter" });
    expect(onCommit).toHaveBeenCalledTimes(1);
  });

  it("uses signed integer text for step-1 adjustments", () => {
    renderField({ label: "对比度", unit: undefined, value: 25, min: -100, max: 100, step: 1 });

    const slider = screen.getByRole("slider", { name: "对比度" });
    expect(slider).toHaveAttribute("aria-valuetext", "+25");
  });

  it("disables both controls when requested", () => {
    renderField({ disabled: true });

    expect(screen.getByRole("slider", { name: "曝光" })).toBeDisabled();
    expect(screen.getByRole("spinbutton", { name: "曝光" })).toBeDisabled();
  });
});
