import { describe, expect, it } from "vitest";

import {
  buildStyleInstruction,
  selectablePersonalStyles,
  STYLE_INSTRUCTION_MAX_CHARS,
} from "@/features/generative/style-instruction";
import { personalStyleItem } from "./personal-style-fixtures";

describe("selectablePersonalStyles", () => {
  it("keeps only published and enabled styles", () => {
    const styles = [
      personalStyleItem({ id: "draft", status: "draft" }),
      personalStyleItem({ id: "disabled-status", status: "disabled" }),
      personalStyleItem({ id: "disabled-flag", status: "published", enabled: false }),
      personalStyleItem({ id: "usable", status: "published", enabled: true }),
    ];

    expect(selectablePersonalStyles(styles).map((style) => style.id)).toEqual(["usable"]);
  });

  it("orders favorites first, then by name and id, without mutating the input", () => {
    const styles = [
      personalStyleItem({ id: "b", name: "乙", status: "published" }),
      personalStyleItem({ id: "a", name: "甲", status: "published" }),
      personalStyleItem({ id: "z", name: "甲", status: "published", favorite: true }),
    ];
    const order = styles.map((style) => style.id);

    expect(selectablePersonalStyles(styles).map((style) => style.id)).toEqual(["z", "a", "b"]);
    expect(styles.map((style) => style.id)).toEqual(order);
  });
});

describe("buildStyleInstruction", () => {
  it("carries the name, signature and description plus the preservation clause", () => {
    const instruction = buildStyleInstruction(personalStyleItem({ status: "published" }));

    expect(instruction).toContain("风格参考：克制的城市叙事");
    expect(instruction).toContain("风格特征：整体偏冷，低饱和；柔和漫射光；颗粒克制");
    expect(instruction).toContain("风格说明：低饱和、偏冷的环境色彩，保留暗部层次与自然街头质感。");
    expect(instruction).toContain("保持区域外像素、主体身份与结构、原有透视和光线方向不变。");
  });

  it("is deterministic for the same style", () => {
    const style = personalStyleItem({ status: "published" });

    expect(buildStyleInstruction(style)).toBe(buildStyleInstruction(style));
  });

  it("skips blank signature entries and an empty description", () => {
    const instruction = buildStyleInstruction(
      personalStyleItem({ signature: ["  ", "颗粒克制"], description: "   " }),
    );

    expect(instruction).toContain("风格特征：颗粒克制");
    expect(instruction).not.toContain("风格说明：");
  });

  it("stays within the prompt limit and keeps the preservation clause", () => {
    const instruction = buildStyleInstruction(
      personalStyleItem({ description: "细".repeat(5000), signature: ["长".repeat(5000)] }),
    );

    expect(instruction.length).toBeLessThanOrEqual(STYLE_INSTRUCTION_MAX_CHARS);
    expect(instruction.endsWith("保持区域外像素、主体身份与结构、原有透视和光线方向不变。")).toBe(true);
  });
});