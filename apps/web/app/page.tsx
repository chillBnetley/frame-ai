import { SiteHeader } from "@/components/site-header";
import { EditorWorkspace } from "@/features/editor/editor-workspace";

export default function Home() {
  return (
    <div className="min-h-dvh">
      <SiteHeader />
      <main className="mx-auto w-full max-w-[1680px] px-4 py-5 sm:px-6 lg:px-8">
        <section aria-labelledby="page-title" className="mb-5 flex flex-col gap-3 border-b border-[#e4e8e5] pb-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.24em] text-[#648176]">
              FRAME <span className="px-1 text-[#b2bcb6]">/</span> IMAGE STUDIO
            </p>
            <h1
              id="page-title"
              className="text-3xl font-semibold leading-[1.08] tracking-[-0.045em] text-white sm:text-[2.65rem]"
              style={{ fontFamily: '"Noto Serif SC", "Source Han Serif SC", "Songti SC", "SimSun", serif' }}
            >
              照片工作台
            </h1>
            <p className="mt-2 text-[13px] tracking-[0.04em] text-white/45">整理画面，找到你想要的感觉。</p>
          </div>
          <p className="mb-1 flex items-center gap-2 border-l-2 border-[#bfd5ca] pl-3 text-xs leading-relaxed tracking-[0.04em] text-white/35 sm:ml-8">
            <span className="size-1.5 shrink-0 rounded-full bg-[#6b9a83]" />
            图片保存在本机
          </p>
        </section>
        <EditorWorkspace />
      </main>
    </div>
  );
}
