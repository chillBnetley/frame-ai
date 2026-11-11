import type { PersonalStyleItem } from "@/types/personal-style";

/** Matches the local-edit textarea limit so a filled instruction is always submittable. */
export const STYLE_INSTRUCTION_MAX_CHARS = 2000;

const PRESERVATION_CLAUSE =
  "仅把上述风格倾向应用到蒙版选中的区域，保持区域外像素、主体身份与结构、原有透视和光线方向不变。";

export function selectablePersonalStyles(
  styles: readonly PersonalStyleItem[],
): PersonalStyleItem[] {
  return styles
    .filter((style) => style.status === "published" && style.enabled)
    .sort(
      (left, right) =>
        Number(right.favorite) - Number(left.favorite) ||
        left.name.localeCompare(right.name) ||
        left.id.localeCompare(right.id),
    );
}

export function buildStyleInstruction(style: PersonalStyleItem): string {
  const lines = [`风格参考：${style.name.trim()}`];
  const signature = style.signature.map((item) => item.trim()).filter((item) => item.length > 0);
  if (signature.length > 0) {
    lines.push(`风格特征：${signature.join("；")}`);
  }
  const description = style.description.trim();
  if (description.length > 0) {
    lines.push(`风格说明：${description}`);
  }
  // The preservation clause must survive truncation, so the body gets the leftovers.
  const budget = STYLE_INSTRUCTION_MAX_CHARS - PRESERVATION_CLAUSE.length - 1;
  return `${lines.join("\n").slice(0, budget)}\n${PRESERVATION_CLAUSE}`;
}