import { CheckCircleIcon, RefreshIcon, ServerIcon } from "@/components/icons";
import type { ApiStatus } from "@/types/image";

const STATUS_STYLES: Record<ApiStatus, { dot: string; text: string; label: string }> = {
  checking: {
    dot: "bg-amber-300 animate-pulse",
    text: "text-white/50",
    label: "检查 API",
  },
  online: {
    dot: "bg-emerald-400 shadow-[0_0_10px_rgba(52,211,153,0.5)]",
    text: "text-emerald-200/80",
    label: "API 已连接",
  },
  offline: {
    dot: "bg-red-400",
    text: "text-red-200/80",
    label: "API 未连接",
  },
};

export function HealthIndicator({ status }: { status: ApiStatus }) {
  const style = STATUS_STYLES[status];
  const Icon = status === "online" ? CheckCircleIcon : status === "offline" ? RefreshIcon : ServerIcon;

  return (
    <span
      role="status"
      aria-live="polite"
      title={status === "offline" ? "请确认 FastAPI 已在 8000 端口启动" : "FastAPI 健康检查"}
      className={`inline-flex items-center gap-2 rounded-full border border-white/8 bg-black/20 px-3 py-1.5 text-[11px] font-medium ${style.text}`}
    >
      <span className={`size-1.5 rounded-full ${style.dot}`} />
      <Icon className="size-3.5 opacity-70" />
      {style.label}
    </span>
  );
}
