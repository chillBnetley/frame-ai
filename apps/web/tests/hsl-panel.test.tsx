import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { HslPanel } from "@/features/editor/components/hsl-panel";
import { HSL_BAND_NAMES, normalizeHsl } from "@/lib/recipe";
import type { HslAdjustments, HslBand, HslBandName } from "@/types/session";

const BAND_LABELS = ["红色", "橙色", "黄色", "绿色", "青色", "蓝色", "紫色", "洋红"];

interface HarnessProps {
  initial?: Partial<Record<HslBandName, Partial<HslBand>>>;
  disabled?: boolean;
  onChange?: (band: HslBandName, key: keyof HslBand, value: number) => void;
  onResetBand?: (band: HslBandName) => void;
  onResetAll?: () => void;
  onCommit?: () => void;
}

function Harness({
  initial,
  disabled,
  onChange,
  onResetBand,
  onResetAll,
  onCommit,
}: HarnessProps) {
  const [hsl, setHsl] = useState<Required<HslAdjustments>>(() => {
    const base = normalizeHsl({});
    for (const band of HSL_BAND_NAMES) {
      const values = initial?.[band];
      if (values) {
        base[band] = { ...base[band], ...values };
      }
    }
    return base;
  });
  return (
    <HslPanel
      hsl={hsl}
      disabled={disabled}
      onChange={(band, key, value) => {
        onChange?.(band, key, value);
        setHsl((current) => ({ ...current, [band]: { ...current[band], [key]: value } }));
      }}
      onResetBand={(band) => {
        onResetBand?.(band);
        setHsl((current) => ({
          ...current,
          [band]: { hue: 0, saturation: 0, luminance: 0 },
        }));
      }}
      onResetAll={() => {
        onResetAll?.();
        setHsl(normalizeHsl({}));
      }}
      onCommit={onCommit ?? (() => {})}
    />
  );
}

describe("HslPanel", () => {
  it("renders all eight bands with the red band active and neutral sliders", () => {
    render(<Harness />);

    for (const label of BAND_LABELS) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "红色" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("group", { name: "HSL 色带" })).toBeInTheDocument();
    expect(screen.getByRole("slider", { name: "红色 色相" })).toHaveValue("0");
    expect(screen.getByRole("slider", { name: "红色 饱和度" })).toHaveValue("0");
    expect(screen.getByRole("slider", { name: "红色 明度" })).toHaveValue("0");
  });

  it("shows the values of the selected band", () => {
    render(
      <Harness
        initial={{ blue: { hue: 25, saturation: -10, luminance: 5 } }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "蓝色" }));

    expect(screen.getByRole("button", { name: "蓝色" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("slider", { name: "蓝色 色相" })).toHaveValue("25");
    expect(screen.getByRole("slider", { name: "蓝色 饱和度" })).toHaveValue("-10");
    expect(screen.getByRole("slider", { name: "蓝色 明度" })).toHaveValue("5");
  });

  it("reports band, key and value when a slider changes and commits", () => {
    const onChange = vi.fn();
    const onCommit = vi.fn();
    render(<Harness onChange={onChange} onCommit={onCommit} />);

    fireEvent.click(screen.getByRole("button", { name: "绿色" }));
    const slider = screen.getByRole("slider", { name: "绿色 饱和度" });
    fireEvent.change(slider, { target: { value: "-40" } });
    fireEvent.pointerUp(slider);

    expect(onChange).toHaveBeenCalledWith("green", "saturation", -40);
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(slider).toHaveValue("-40");
  });

  it("resets the active band only", () => {
    const onResetBand = vi.fn();
    const onResetAll = vi.fn();
    render(
      <Harness
        initial={{
          red: { hue: 12, saturation: 6, luminance: -3 },
          aqua: { luminance: 8 },
        }}
        onResetBand={onResetBand}
        onResetAll={onResetAll}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "重置当前色带" }));

    expect(onResetBand).toHaveBeenCalledWith("red");
    expect(onResetAll).not.toHaveBeenCalled();
    expect(screen.getByRole("slider", { name: "红色 色相" })).toHaveValue("0");

    fireEvent.click(screen.getByRole("button", { name: "青色" }));
    expect(screen.getByRole("slider", { name: "青色 明度" })).toHaveValue("8");
  });

  it("resets every band and disables the reset action afterwards", () => {
    const onResetAll = vi.fn();
    render(
      <Harness initial={{ orange: { saturation: 20 } }} onResetAll={onResetAll} />,
    );

    const resetAll = screen.getByRole("button", { name: "重置全部 HSL" });
    expect(resetAll).toBeEnabled();
    fireEvent.click(resetAll);

    expect(onResetAll).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "重置全部 HSL" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "重置当前色带" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "橙色" }));
    expect(screen.getByRole("slider", { name: "橙色 饱和度" })).toHaveValue("0");
  });

  it("disables every control when disabled", () => {
    render(<Harness disabled initial={{ red: { hue: 10 } }} />);

    for (const label of BAND_LABELS) {
      expect(screen.getByRole("button", { name: label })).toBeDisabled();
    }
    expect(screen.getByRole("slider", { name: "红色 色相" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "重置当前色带" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "重置全部 HSL" })).toBeDisabled();
  });
});
