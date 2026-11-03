import { SiteHeader } from "@/components/site-header";
import { EditorWorkspace } from "@/features/editor/editor-workspace";

export default function Home() {
  return (
    <div className="min-h-dvh">
      <SiteHeader />
      <main className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8">
        <section aria-labelledby="page-title" className="mb-6 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h1 id="page-title" className="text-2xl font-semibold tracking-tight text-white sm:text-3xl">
              照片工作台
            </h1>
            <p className="mt-1 text-sm text-white/45">整理画面，找到你想要的感觉。</p>
          </div>
          <p className="text-xs text-white/35">图片保存在本机</p>
        </section>
        <EditorWorkspace />
      </main>
    </div>
  );
}
