"use client";

import Link from "next/link";
import Image from "next/image";
import { useState } from "react";

import { SettingsIcon } from "@/components/icons";
import { SettingsDialog } from "@/components/settings-dialog";

export function SiteHeader() {
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <>
      <header className="sticky top-0 z-40 border-b border-white/8 bg-[#08090a]/80 shadow-[0_4px_24px_rgba(24,50,38,0.04)] backdrop-blur-xl">
      <div className="mx-auto flex h-15 w-full max-w-[1680px] items-center justify-between px-4 sm:px-6 lg:px-8">
        <Link
          href="/"
          className="group flex min-h-11 items-center gap-2.5 rounded-lg focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent"
          aria-label="FRAME AI 首页"
        >
          <Image
            src="/brand/frame-ai-mark-light.png"
            alt=""
            width={36}
            height={36}
            className="size-9 rounded-[10px] border border-[#e0e6e1] bg-white object-cover shadow-[0_2px_8px_rgba(30,55,42,0.10)] transition-transform duration-200 group-hover:scale-[1.04]"
            priority
          />
          <span className="pl-0.5 text-[13px] font-light tracking-[0.24em] text-white sm:text-sm" style={{ fontFamily: 'Avenir, "Avenir Next", Montserrat, Inter, sans-serif' }}>
            FRAME AI
          </span>
        </Link>
        <nav aria-label="主导航" className="hidden items-center gap-1 md:flex">
          <Link
            href="/"
            className="inline-flex min-h-9 items-center rounded-full px-3 text-xs font-medium text-[#69716c] transition-colors hover:bg-[#f1f4f2] hover:text-[#2c3a34] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            照片工作台
          </Link>
          <Link
            href="/master-vision"
            className="inline-flex min-h-9 items-center rounded-full bg-[#eaf3ef] px-3 text-xs font-medium text-[#1f6a5a] transition-colors hover:bg-[#dfeee8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            Master Vision
          </Link>
        </nav>
        <div className="flex items-center gap-2">
          <Link
            href="/master-vision"
            className="inline-flex min-h-11 items-center rounded-xl border border-[#d7dfda] bg-white px-3 text-xs font-medium text-[#277a68] md:hidden focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            Master Vision
          </Link>
          <button
            type="button"
            onClick={() => setSettingsOpen(true)}
            aria-haspopup="dialog"
          className="inline-flex min-h-11 items-center gap-1.5 rounded-xl border border-white/12 bg-gradient-to-b from-white/[0.12] to-white/[0.03] px-3 text-xs text-white/65 shadow-[inset_0_1px_0_rgba(255,255,255,0.18)] transition-all duration-200 hover:-translate-y-px hover:border-accent/30 hover:from-accent/[0.12] hover:to-accent/[0.04] hover:shadow-[inset_0_1px_0_rgba(255,255,255,0.32),0_5px_14px_rgba(39,122,104,0.12)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            <SettingsIcon className="size-4" />
            <span className="hidden sm:inline">模型设置</span>
            <span className="sr-only sm:hidden">模型设置</span>
          </button>
          <span className="hidden items-center gap-2 rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 text-xs text-white/55 sm:inline-flex">
            <span className="size-1.5 rounded-full bg-accent" />
            本地工作区
          </span>
        </div>
        </div>
      </header>
      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </>
  );
}
