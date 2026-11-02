import {
  ImageIcon,
  LockIcon,
  ShieldCheckIcon,
  SparkleIcon,
} from "@/components/icons";
import { SiteHeader } from "@/components/site-header";
import { EditorWorkspace } from "@/features/editor/editor-workspace";

const SCOPE_ITEMS = [
  {
    icon: ShieldCheckIcon,
    number: "01",
    title: "双重校验",
    description: "同时核验 MIME 与真实图片内容，像素、大小和格式边界由服务端强制。",
  },
  {
    icon: LockIcon,
    number: "02",
    title: "不可变原图",
    description: "随机文件名写入本地数据目录，用户文件名永远不参与存储路径。",
  },
  {
    icon: SparkleIcon,
    number: "03",
    title: "可回退起点",
    description: "阶段 2 起，每次编辑都从这张原图重算，而不是反复覆盖像素。",
  },
];

export default function Home() {
  return (
    <div className="relative flex min-h-dvh flex-col">
      <SiteHeader />

      <main className="mx-auto w-full max-w-6xl flex-1 px-5 sm:px-8">
        <section className="pb-10 pt-14 sm:pb-12 sm:pt-20">
          <div className="flex items-center gap-3">
            <span className="h-px w-8 bg-accent/70" />
            <p className="font-mono text-[10px] font-medium uppercase tracking-[0.24em] text-accent/80">
              Phase 01 / Foundation
            </p>
          </div>

          <h1 className="mt-6 max-w-3xl text-balance text-[clamp(2.7rem,7vw,5.4rem)] font-medium leading-[0.94] tracking-[-0.05em] text-white">
            先看清原图，
            <br />
            <span className="text-white/30">再进入编辑。</span>
          </h1>

          <div className="mt-7 flex max-w-3xl flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
            <p className="max-w-xl text-sm leading-7 text-white/45 sm:text-base sm:leading-8">
              上传一张照片。FRAME AI 会在服务端校验并保存不可变原图，
              为接下来的风格配方、手动微调与前后对比建立干净起点。
            </p>
            <div className="flex shrink-0 items-center gap-2 font-mono text-[10px] uppercase tracking-[0.14em] text-white/30">
              <ImageIcon className="size-3.5" />
              JPEG / PNG / WebP
            </div>
          </div>
        </section>

        <EditorWorkspace />

        <section aria-label="阶段 1 能力范围" className="mt-5 grid gap-3 sm:grid-cols-3">
          {SCOPE_ITEMS.map((item) => (
            <article
              key={item.number}
              className="group rounded-2xl border border-white/8 bg-white/[0.015] p-5 transition-colors hover:border-white/15 hover:bg-white/[0.03]"
            >
              <div className="flex items-center justify-between">
                <span className="grid size-9 place-items-center rounded-lg border border-white/10 bg-white/[0.03] text-white/55 transition-colors group-hover:text-accent">
                  <item.icon className="size-4" />
                </span>
                <span className="font-mono text-[10px] tracking-[0.16em] text-white/20">
                  {item.number}
                </span>
              </div>
              <h3 className="mt-4 text-sm font-medium text-white/85">{item.title}</h3>
              <p className="mt-2 text-xs leading-6 text-white/35">{item.description}</p>
            </article>
          ))}
        </section>
      </main>

      <footer className="mx-auto mt-16 w-full max-w-6xl border-t border-white/8 px-5 py-6 sm:px-8">
        <div className="flex flex-col gap-2 text-[11px] text-white/30 sm:flex-row sm:items-center sm:justify-between">
          <p>FRAME AI · Phase 01 可运行骨架</p>
          <p className="inline-flex items-center gap-2">
            <LockIcon className="size-3.5" />
            原图不离开本机 · 阶段 1 不调用 AI 模型
          </p>
        </div>
      </footer>
    </div>
  );
}
