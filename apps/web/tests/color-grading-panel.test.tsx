import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ColorGradingPanel } from "@/features/editor/components/color-grading-panel";
import {
  COLOR_GRADE_ZONE_NAMES,
  normalizeColorGrading,
} from "@/lib/recipe";
import type {
  ColorGradeZone,
  ColorGradeZoneName,
  ColorGrading,
} from "@/types/session";

interface HarnessProps {
  initial?: Partial<
    Record<ColorGradeZoneName, Partial<ColorGradeZone>> & {
      balance?: number;
      blending?: number;
    }
  >;
  disabled?: boolean;
  onChange?: (
    zone: ColorGradeZoneName,
    key: keyof ColorGradeZone,
    value: number,
  ) => void;
  onOptionChange?: (key: "balance" | "blending", value: number) => void;
  onResetZone?: (zone: ColorGradeZoneName) => void;
  onResetAll?: () => void;
  onCommit?: () => void;
}

function Harness({
  initial,
  disabled,
  onChange,
  onOptionChange,
  onResetZone,
  onResetAll,
  onCommit,
}: HarnessProps) {
  const [grading, setGrading] = useState<Required<ColorGrading>>(() => {
    const base = normalizeColorGrading({});
    for (const zone of COLOR_GRADE_ZONE_NAMES) {
      const values = initial?.[zone];
      if (values) {
        base[zone] = { ...base[zone], ...values };
      }
    }
    return {
      ...base,
      balance: initial?.balance ?? base.balance,
      blending: initial?.blending ?? base.blending,
    };
  });
  return (
    <ColorGradingPanel
      grading={grading}
      disabled={disabled}
      onChange={(zone, key, value) => {
        onChange?.(zone, key, value);
        setGrading((current) => ({
          ...current,
          [zone]: { ...current[zone], [key]: value },
        }));
      }}
      onOptionChange={(key, value) => {
        onOptionChange?.(key, value);
        setGrading((current) => ({ ...current, [key]: value }));
      }}
      onResetZone={(zone) => {
        onResetZone?.(zone);
        setGrading((current) => ({
          ...current,
          [zone]: { hue: 0, saturation: 0 },
        }));
      }}
      onResetAll={() => {
        onResetAll?.();
        setGrading(normalizeColorGrading({}));
      }}
      onCommit={onCommit ?? (() => {})}
    />
  );
}

describe("ColorGradingPanel", () => {
  it("renders three zones with the shadows zone active and neutral defaults", () => {
    render(<Harness />);

    for (const label of ["阴影", "中间调", "高光"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "阴影" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("group", { name: "颜色分级区域" })).toBeInTheDocument();
    expect(screen.getByRole("slider", { name: "阴影 色相" })).toHaveValue("0");
    expect(screen.getByRole("slider", { name: "阴影 强度" })).toHaveValue("0");
    expect(screen.getByRole("slider", { name: "平衡" })).toHaveValue("0");
    expect(screen.getByRole("slider", { name: "混合范围" })).toHaveValue("50");
  });

  it("shows the values of the selected zone", () => {
    render(
      <Harness
        initial={{
          highlights: { hue: 45, saturation: 30 },
          balance: 10,
          blending: 70,
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "高光" }));

    expect(screen.getByRole("button", { name: "高光" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("slider", { name: "高光 色相" })).toHaveValue("45");
    expect(screen.getByRole("slider", { name: "高光 强度" })).toHaveValue("30");
    expect(screen.getByRole("slider", { name: "平衡" })).toHaveValue("10");
    expect(screen.getByRole("slider", { name: "混合范围" })).toHaveValue("70");
  });

  it("reports zone, key and value when a slider changes and commits", () => {
    const onChange = vi.fn();
    const onCommit = vi.fn();
    render(<Harness onChange={onChange} onCommit={onCommit} />);

    fireEvent.click(screen.getByRole("button", { name: "中间调" }));
    const slider = screen.getByRole("slider", { name: "中间调 强度" });
    fireEvent.change(slider, { target: { value: "35" } });
    fireEvent.pointerUp(slider);

    expect(onChange).toHaveBeenCalledWith("midtones", "saturation", 35);
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(slider).toHaveValue("35");
  });

  it("reports balance and blending changes", () => {
    const onOptionChange = vi.fn();
    render(<Harness onOptionChange={onOptionChange} />);

    fireEvent.change(screen.getByRole("slider", { name: "平衡" }), {
      target: { value: "-20" },
    });
    fireEvent.change(screen.getByRole("slider", { name: "混合范围" }), {
      target: { value: "80" },
    });

    expect(onOptionChange).toHaveBeenCalledWith("balance", -20);
    expect(onOptionChange).toHaveBeenCalledWith("blending", 80);
  });

  it("resets the active zone only", () => {
    const onResetZone = vi.fn();
    const onResetAll = vi.fn();
    render(
      <Harness
        initial={{
          shadows: { hue: 220, saturation: 25 },
          midtones: { hue: 160, saturation: 15 },
        }}
        onResetZone={onResetZone}
        onResetAll={onResetAll}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "重置当前区域" }));

    expect(onResetZone).toHaveBeenCalledWith("shadows");
    expect(onResetAll).not.toHaveBeenCalled();
    expect(screen.getByRole("slider", { name: "阴影 色相" })).toHaveValue("0");
    expect(screen.getByRole("slider", { name: "阴影 强度" })).toHaveValue("0");

    fireEvent.click(screen.getByRole("button", { name: "中间调" }));
    expect(screen.getByRole("slider", { name: "中间调 强度" })).toHaveValue("15");
  });

  it("resets every zone and disables the reset actions afterwards", () => {
    const onResetAll = vi.fn();
    render(
      <Harness
        initial={{ highlights: { hue: 45, saturation: 20 } }}
        onResetAll={onResetAll}
      />,
    );

    const resetAll = screen.getByRole("button", { name: "重置全部分级" });
    expect(resetAll).toBeEnabled();
    fireEvent.click(resetAll);

    expect(onResetAll).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "重置全部分级" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "重置当前区域" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "高光" }));
    expect(screen.getByRole("slider", { name: "高光 强度" })).toHaveValue("0");
  });

  it("tints the zone swatch only when strength is above zero", () => {
    render(
      <Harness
        initial={{
          shadows: { hue: 220, saturation: 25 },
          highlights: { hue: 45, saturation: 0 },
        }}
      />,
    );

    const shadows = screen.getByTestId("grading-swatch-shadows");
    const highlights = screen.getByTestId("grading-swatch-highlights");
    expect(shadows.style.backgroundColor).toBe("rgb(43, 108, 238)");
    expect(highlights.style.backgroundColor).toBe("transparent");
  });

  it("disables every control when disabled", () => {
    render(<Harness disabled initial={{ shadows: { hue: 220, saturation: 25 } }} />);

    for (const label of ["阴影", "中间调", "高光"]) {
      expect(screen.getByRole("button", { name: label })).toBeDisabled();
    }
    expect(screen.getByRole("slider", { name: "阴影 色相" })).toBeDisabled();
    expect(screen.getByRole("slider", { name: "阴影 强度" })).toBeDisabled();
    expect(screen.getByRole("slider", { name: "平衡" })).toBeDisabled();
    expect(screen.getByRole("slider", { name: "混合范围" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "重置当前区域" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "重置全部分级" })).toBeDisabled();
  });
});
