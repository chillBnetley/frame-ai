import Link from "next/link";

import { FrameMark } from "@/components/icons";

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-white/8 bg-[#08090a]/80 backdrop-blur-xl">
      <div className="mx-auto flex h-15 w-full max-w-[1440px] items-center justify-between px-4 sm:px-6 lg:px-8">
        <Link
          href="/"
          className="group flex min-h-11 items-center gap-2.5 rounded-lg focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent"
          aria-label="FRAME AI 首页"
        >
          <span className="grid size-8 place-items-center rounded-lg border border-white/12 bg-white/[0.04] text-accent transition-colors group-hover:bg-white/[0.08]">
            <FrameMark className="size-4.5" />
          </span>
          <span className="text-sm font-semibold tracking-tight text-white">FRAME AI</span>
        </Link>
        <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 text-xs text-white/55">
          <span className="size-1.5 rounded-full bg-accent" />
          本地工作区
        </span>
      </div>
    </header>
  );
}
