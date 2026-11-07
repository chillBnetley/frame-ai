import { describe, expect, it } from "vitest";

import {
  findStyle,
  groupStylesByScene,
  STYLE_CATEGORY_LABELS,
} from "@/features/photographer/presentation";
import { styleCatalog } from "./photographer-fixtures";

describe("style picker helpers", () => {
  it("lists scene-capable styles first without duplicating them", () => {
    const groups = groupStylesByScene(styleCatalog(), "portrait");

    expect(groups.recommended.map((style) => style.id)).toEqual([
      "portrait",
      "clear_portrait",
      "monochrome",
    ]);
    expect(groups.others.map((style) => style.id)).toEqual([
      "landscape",
      "street",
      "cinematic",
    ]);
  });

  it("keeps the whole catalog selectable before an analysis exists", () => {
    const groups = groupStylesByScene(styleCatalog(), null);

    expect(groups.recommended).toHaveLength(0);
    expect(groups.others).toHaveLength(6);
  });

  it("resolves a selection and tolerates a style that is gone", () => {
    const catalog = styleCatalog();

    expect(findStyle(catalog, "monochrome")?.name).toBe("黑白纪实");
    expect(findStyle(catalog, "removed_style")).toBeNull();
    expect(findStyle(catalog, null)).toBeNull();
  });

  it("labels both style categories", () => {
    expect(STYLE_CATEGORY_LABELS.scene).toBe("场景风格");
    expect(STYLE_CATEGORY_LABELS.creative).toBe("创作风格");
  });
});
