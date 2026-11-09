import type { ReactNode } from "react";

export function MasterVisionStatus({
  tone,
  title,
  children,
  action,
}: {
  tone: "info" | "error" | "success";
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  const palette = {
    info: "border-[#dbe5e0] bg-[#f4f8f6] text-[#365148]",
    error: "border-[#efc9c4] bg-[#fdf4f2] text-[#8a3a2e]",
    success: "border-[#c4ddcf] bg-[#f1f8f4] text-[#25624f]",
  }[tone];

  return (
    <div role={tone === "error" ? "alert" : "status"} className={`flex flex-wrap items-start justify-between gap-3 rounded-xl border px-4 py-3 ${palette}`}>
      <div className="min-w-0">
        <p className="text-xs font-semibold tracking-[0.02em]">{title}</p>
        {children !== undefined && <div className="mt-1 text-xs leading-relaxed opacity-80">{children}</div>}
      </div>
      {action}
    </div>
  );
}
