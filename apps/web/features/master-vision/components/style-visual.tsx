import type { StyleKind } from "@/types/style-library";

import { styleGradient } from "../presentation";

export function StyleVisual({
  styleId,
  kind,
  label = "示意视觉 · 非原作",
  className = "",
}: {
  styleId: string;
  kind: StyleKind;
  label?: string;
  className?: string;
}) {
  return (
    <div
      aria-hidden="true"
      className={`relative overflow-hidden ${className}`}
      style={{ backgroundImage: styleGradient(styleId, kind) }}
    >
      <div
        className="absolute inset-0 opacity-35"
        style={{
          backgroundImage:
            "repeating-linear-gradient(115deg, rgba(255,255,255,.22) 0 1px, transparent 1px 9px)",
        }}
      />
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,transparent_35%,rgba(9,16,20,.42))]" />
      <span className="absolute bottom-2.5 left-3 rounded-full border border-[rgba(255,255,255,0.35)] bg-[rgba(0,0,0,0.25)] px-2 py-0.5 text-[9px] font-medium tracking-[0.12em] text-[#f7faf8]/85">
        {label}
      </span>
    </div>
  );
}
