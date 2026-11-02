import Link from "next/link";

import { FrameMark } from "@/components/icons";

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-white/8 bg-[#08090a]/80 backdrop-blur-xl">
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between px-5 sm:px-8">
        <Link
          href="/"
          className="group flex min-h-11 items-center gap-3 rounded-lg focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent"
          aria-label="FRAME AI 首页"
        >
          <span className="grid size-9 place-items-center rounded-lg border border-white/12 bg-white/[0.04] text-accent transition-colors group-hover:border-accent/40 group-hover:bg-accent/10">
            <FrameMark className="size-5" />
          </span>
          <span className="text-sm font-semibold tracking-[0.22em] text-white">
            FRAME <span className="text-white/40">AI</span>
          </span>
        </Link>

        <div className="flex items-center gap-4">
          <span className="hidden text-[10px] font-medium uppercase tracking-[0.22em] text-white/35 sm:inline">
            Phase 01 · Upload &amp; Preview
          </span>
          <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 text-[11px] text-white/55">
            <span className="size-1.5 rounded-full bg-accent shadow-[0_0_10px_var(--color-accent)]" />
            本地优先
          </span>
        </div>
      </div>
    </header>
  );
}
