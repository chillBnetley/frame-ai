import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { LocalAdjustmentsPanel } from "@/features/editor/components/local-adjustments-panel";
import { normalizeLocalAdjustmentValues, normalizeRecipe } from "@/lib/recipe";
import type { Size } from "@/lib/mask-geometry";
import type { EditRecipe, EditorRecipe } from "@/types/session";

interface HarnessProps {
  initial?: Partial<EditRecipe>;
  disabled?: boolean;
  layersEnabled?: boolean;
  previewUrl?: string | null;
  previewWidth?: number;
  previewHeight?: number;
  sourceSize?: Size | null;
  renderWarnings?: readonly string[];
  onChange?: (recipe: EditorRecipe) => void;
  onCommit?: () => void;
}

function Harness({
  initial,
  disabled,
  layersEnabled = false,
  previewUrl = "/api/v1/previews/mock",
  previewWidth = 800,
  previewHeight = 600,
  sourceSize = { width: 800, height: 600 },
  renderWarnings,
  onChange,
  onCommit,
}: HarnessProps) {
  const [recipe, setRecipe] = useState<EditorRecipe>(() => normalizeRecipe(initial));
  return (
    <LocalAdjustmentsPanel
      recipe={recipe}
      previewUrl={previewUrl}
      previewWidth={previewWidth}
      previewHeight={previewHeight}
      sourceSize={sourceSize}
      renderWarnings={renderWarnings}
      disabled={disabled}
      layersEnabled={layersEnabled}
      onChange={(next) => {
        onChange?.(next);
        setRecipe(next);
      }}
      onCommit={onCommit ?? (() => {})}
    />
  );
}

function renderPanel(props: HarnessProps = {}) {
  const onChange = vi.fn();
  const onCommit = vi.fn();
  const result = render(
    <Harness {...props} onChange={onChange} onCommit={onCommit} />,
  );
  return { onChange, onCommit, unmount: result.unmount };
}

function lastRecipe(onChange: ReturnType<typeof vi.fn>): EditorRecipe {
  return onChange.mock.calls.at(-1)?.[0] as EditorRecipe;
}

const RECT_RECIPE: Partial<EditRecipe> = {
  masks: [
    {
      id: "mask_1",
      shape: "rectangle",
      source: "user",
      coordinateSpace: "source-normalized",
      x: 0.2,
      y: 0.2,
      width: 0.4,
      height: 0.4,
      feather: 20,
      opacity: 100,
      inverted: false,
    },
  ],
  localAdjustments: [
    {
      id: "local_1",
      maskId: "mask_1",
      enabled: true,
      name: null,
      blendMode: "normal",
      opacity: 100,
      order: 0,
      adjustments: normalizeLocalAdjustmentValues({ exposureEv: 0.5 }),
    },
  ],
};

function outlinePointCount(): number {
  const points = screen.getByTestId("mask-outline").getAttribute("points") ?? "";
  return points.trim().split(/\s+/).filter(Boolean).length;
}

describe("LocalAdjustmentsPanel", () => {
  it("starts empty and explains that person and sky masks are unavailable", () => {
    renderPanel();

    expect(screen.getByText(/尚未添加局部调整/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "人物蒙版" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "天空蒙版" })).toBeDisabled();
    expect(
      screen.getByText(/未接入真实的人物\/天空分割模型/),
    ).toBeInTheDocument();
    expect(screen.getByText("0 / 20")).toBeInTheDocument();
  });

  it("creates rectangle, ellipse and full-image adjustments with matching masks", async () => {
    const { onChange, onCommit } = renderPanel();

    await userEvent.click(screen.getByRole("button", { name: "添加矩形区域" }));
    let recipe = lastRecipe(onChange);
    expect(recipe.masks).toHaveLength(1);
    expect(recipe.masks[0]?.shape).toBe("rectangle");
    expect(recipe.localAdjustments[0]?.maskId).toBe(recipe.masks[0]?.id);

    await userEvent.click(screen.getByRole("button", { name: "添加椭圆区域" }));
    recipe = lastRecipe(onChange);
    expect(recipe.masks).toHaveLength(2);
    expect(recipe.masks[1]?.shape).toBe("ellipse");
    expect(recipe.localAdjustments[1]?.maskId).toBe(recipe.masks[1]?.id);

    await userEvent.click(
      screen.getByRole("button", { name: "添加全图局部调整" }),
    );
    recipe = lastRecipe(onChange);
    expect(recipe.masks).toHaveLength(2);
    expect(recipe.localAdjustments[2]?.maskId).toBe("full");
    expect(onCommit).toHaveBeenCalledTimes(3);
    expect(screen.getByText("3 / 20")).toBeInTheDocument();
  });

  it("edits local values and mask geometry", async () => {
    const { onChange, onCommit } = renderPanel({ initial: RECT_RECIPE });

    const exposure = screen.getByRole("slider", { name: "局部曝光" });
    fireEvent.change(exposure, { target: { value: "1.25" } });
    fireEvent.pointerUp(exposure);
    expect(
      lastRecipe(onChange).localAdjustments[0]?.adjustments?.exposureEv,
    ).toBe(1.25);

    const feather = screen.getByRole("slider", { name: "局部羽化" });
    fireEvent.change(feather, { target: { value: "35" } });
    fireEvent.pointerUp(feather);
    expect(lastRecipe(onChange).masks[0]?.feather).toBe(35);

    const opacity = screen.getByRole("slider", { name: "局部不透明度" });
    fireEvent.change(opacity, { target: { value: "60" } });
    fireEvent.pointerUp(opacity);
    expect(lastRecipe(onChange).masks[0]?.opacity).toBe(60);

    const x = screen.getByRole("spinbutton", { name: "区域左侧 x（%）" });
    fireEvent.change(x, { target: { value: "12.5" } });
    fireEvent.blur(x);
    expect(lastRecipe(onChange).masks[0]?.x).toBe(0.125);
    expect(onCommit).toHaveBeenCalled();

    fireEvent.click(screen.getByRole("checkbox", { name: "反选蒙版（调整区域外）" }));
    expect(lastRecipe(onChange).masks[0]?.inverted).toBe(true);
  });

  it("switches between full, rectangle and ellipse masks", async () => {
    const { onChange } = renderPanel({ initial: RECT_RECIPE });

    await userEvent.click(screen.getByRole("button", { name: "椭圆" }));
    expect(lastRecipe(onChange).masks[0]?.shape).toBe("ellipse");

    await userEvent.click(screen.getByRole("button", { name: "全图" }));
    let recipe = lastRecipe(onChange);
    expect(recipe.localAdjustments[0]?.maskId).toBe("full");
    expect(recipe.masks).toEqual([]);

    await userEvent.click(screen.getByRole("button", { name: "矩形" }));
    recipe = lastRecipe(onChange);
    expect(recipe.masks).toHaveLength(1);
    expect(recipe.localAdjustments[0]?.maskId).toBe(recipe.masks[0]?.id);
  });

  it("toggles, resets and deletes a local adjustment", async () => {
    const { onChange, onCommit } = renderPanel({ initial: RECT_RECIPE });

    const enable = screen.getByRole("checkbox", { name: "启用局部 1" });
    fireEvent.click(enable);
    expect(lastRecipe(onChange).localAdjustments[0]?.enabled).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "重置局部参数" }));
    expect(
      lastRecipe(onChange).localAdjustments[0]?.adjustments?.exposureEv,
    ).toBe(0);

    await userEvent.click(screen.getByRole("button", { name: "删除局部 1" }));
    const recipe = lastRecipe(onChange);
    expect(recipe.localAdjustments).toEqual([]);
    expect(recipe.masks).toEqual([]);
    expect(onCommit).toHaveBeenCalled();
  });

  it("warns about a missing mask and lets the user delete the adjustment", async () => {
    const { onChange } = renderPanel({
      initial: {
        localAdjustments: [
          {
            id: "local_missing",
            maskId: "mask_missing",
            enabled: true,
            name: null,
            blendMode: "normal",
            opacity: 100,
            order: 0,
            adjustments: normalizeLocalAdjustmentValues({ exposureEv: 1 }),
          },
        ],
      },
    });

    expect(screen.getByText("局部 1 · 蒙版缺失")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/蒙版缺失/);
    expect(screen.getByRole("checkbox", { name: "启用局部 1" })).toBeDisabled();
    expect(
      screen.queryByRole("slider", { name: "局部曝光" }),
    ).not.toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "删除该局部调整" }),
    );
    expect(lastRecipe(onChange).localAdjustments).toEqual([]);
  });

  it("reports when the server skipped a dangling mask reference", () => {
    renderPanel({
      initial: {
        localAdjustments: [
          {
            id: "local_missing",
            maskId: "mask_missing",
            enabled: true,
            name: null,
            blendMode: "normal",
            opacity: 100,
            order: 0,
            adjustments: normalizeLocalAdjustmentValues({ exposureEv: 1 }),
          },
        ],
      },
      renderWarnings: ["local_mask_missing:mask_missing"],
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "服务器渲染已跳过此调整：引用的选区已不存在。",
    );
  });

  it("flags a stale skipped render even when the mask exists locally", () => {
    renderPanel({
      initial: RECT_RECIPE,
      renderWarnings: ["local_mask_missing:mask_1"],
    });

    expect(screen.getByText("局部 1 · 矩形 · 已跳过")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "最近一次预览渲染已跳过此调整：请求时的选区引用已失效。",
    );
  });

  it("renders rectangle and ellipse outlines with feather guides", () => {
    const first = renderPanel({ initial: RECT_RECIPE });
    expect(outlinePointCount()).toBe(4);
    expect(screen.getByTestId("mask-inner-outline")).toBeInTheDocument();
    first.unmount();

    renderPanel({
      initial: {
        ...RECT_RECIPE,
        masks: [{ ...RECT_RECIPE.masks![0], shape: "ellipse" as const }],
      },
    });
    expect(outlinePointCount()).toBe(64);
  });

  it("falls back to preview dimensions when the source size is unknown", () => {
    renderPanel({ initial: RECT_RECIPE, sourceSize: null });
    expect(screen.getByAltText("局部蒙版预览")).toHaveAttribute(
      "src",
      "/api/v1/previews/mock",
    );
    expect(outlinePointCount()).toBe(4);
  });

  it("replaces an expired reference image with a note and keeps the canvas usable", () => {
    renderPanel({ initial: RECT_RECIPE });

    fireEvent.error(screen.getByAltText("局部蒙版预览"));

    expect(screen.queryByAltText("局部蒙版预览")).not.toBeInTheDocument();
    expect(screen.getByText(/参考图已过期/)).toBeInTheDocument();
    expect(screen.getByTestId("mask-outline")).toBeInTheDocument();
  });

  it("restores the reference image when a new preview arrives", () => {
    const { rerender } = render(
      <Harness initial={RECT_RECIPE} onChange={vi.fn()} onCommit={() => {}} />,
    );
    fireEvent.error(screen.getByAltText("局部蒙版预览"));
    expect(screen.queryByAltText("局部蒙版预览")).not.toBeInTheDocument();

    rerender(
      <Harness
        initial={RECT_RECIPE}
        previewUrl="/api/v1/previews/next"
        onChange={vi.fn()}
        onCommit={() => {}}
      />,
    );

    expect(screen.getByAltText("局部蒙版预览")).toHaveAttribute(
      "src",
      "/api/v1/previews/next",
    );
  });

  it("disables every control when the panel is disabled", () => {
    renderPanel({ initial: RECT_RECIPE, disabled: true });

    for (const name of [
      "添加矩形区域",
      "添加椭圆区域",
      "添加全图局部调整",
      "人物蒙版",
      "天空蒙版",
      "矩形",
      "椭圆",
      "删除局部 1",
      "重置局部参数",
      "删除局部调整",
    ]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
    expect(screen.getByRole("checkbox", { name: "启用局部 1" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "反选蒙版（调整区域外）" })).toBeDisabled();
    expect(screen.getByRole("slider", { name: "局部曝光" })).toBeDisabled();
    expect(screen.getByRole("slider", { name: "局部羽化" })).toBeDisabled();
    expect(
      screen.getByRole("spinbutton", { name: "区域左侧 x（%）" }),
    ).toBeDisabled();
  });
});

const LAYERED_RECIPE: Partial<EditRecipe> = {
  localAdjustments: [
    {
      id: "local_1",
      maskId: "full",
      enabled: true,
      name: null,
      blendMode: "normal",
      opacity: 100,
      order: 0,
      adjustments: normalizeLocalAdjustmentValues({ exposureEv: 0.5 }),
    },
    {
      id: "local_2",
      maskId: "full",
      enabled: true,
      name: "Second",
      blendMode: "normal",
      opacity: 100,
      order: 1,
      adjustments: normalizeLocalAdjustmentValues({ contrast: 10 }),
    },
  ],
};

describe("LocalAdjustmentsPanel layer controls", () => {
  it("keeps the legacy panel when the feature flag is off", () => {
    renderPanel({ initial: LAYERED_RECIPE });

    expect(screen.queryByRole("button", { name: /上移图层/ })).toBeNull();
    expect(screen.queryByRole("combobox", { name: /混合模式/ })).toBeNull();
    expect(screen.queryByRole("spinbutton", { name: "图层不透明度" })).toBeNull();
  });

  it("reorders, renames visibility, blends and deletes rows when enabled", async () => {
    const { onChange } = renderPanel({ initial: LAYERED_RECIPE, layersEnabled: true });

    await userEvent.click(screen.getByRole("button", { name: "上移图层 2" }));
    expect(lastRecipe(onChange).localAdjustments.map((item) => item.id)).toEqual([
      "local_2",
      "local_1",
    ]);
    expect(lastRecipe(onChange).localAdjustments.map((item) => item.order)).toEqual([0, 1]);

    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "混合模式 1" }),
      "screen",
    );
    expect(lastRecipe(onChange).localAdjustments[0]?.blendMode).toBe("screen");

    const opacity = screen.getByRole("spinbutton", { name: "图层不透明度" });
    await userEvent.clear(opacity);
    await userEvent.type(opacity, "40{Enter}");
    expect(lastRecipe(onChange).localAdjustments[0]?.opacity).toBe(40);

    await userEvent.click(screen.getByRole("checkbox", { name: "启用局部 1" }));
    expect(lastRecipe(onChange).localAdjustments[0]?.enabled).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "删除局部 2" }));
    expect(lastRecipe(onChange).localAdjustments).toHaveLength(1);
  });
});

describe("LocalAdjustmentsPanel layer capacity", () => {
  it("caps the layer UI at 16 even though the model allows 20", () => {
    const many = Array.from({ length: 16 }, (_, index) => ({
      id: `local_${index}`,
      maskId: "full",
      enabled: true,
      name: null,
      blendMode: "normal" as const,
      opacity: 100,
      order: index,
      adjustments: normalizeLocalAdjustmentValues({ exposureEv: 0.1 }),
    }));

    renderPanel({ initial: { localAdjustments: many }, layersEnabled: true });

    expect(screen.getByText("16 / 16")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "添加全图局部调整" }),
    ).toBeDisabled();
  });
});
