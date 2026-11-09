"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { ArrowRightIcon } from "@/components/icons";
import { MasterVisionStatus } from "@/features/master-vision/components/status";
import { ApiClientError } from "@/lib/api/client";
import {
  addPersonalStyleReferences,
  createPersonalStyle,
} from "@/lib/api/personal-style";

import { ReferenceSelection, type SelectedReference } from "./reference-selection";
import { VisualDnaNav } from "./visual-dna-nav";

const SUGGESTED_MIN = 5;

export function VisualDnaCreate() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selected, setSelected] = useState<SelectedReference[]>([]);
  const [consent, setConsent] = useState(false);
  const [autoAnalyze, setAutoAnalyze] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createdStyleId, setCreatedStyleId] = useState<string | null>(null);

  const canSubmit =
    name.trim().length > 0 &&
    description.trim().length > 0 &&
    selected.length > 0 &&
    consent &&
    !busy;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    let styleId = createdStyleId;
    try {
      if (styleId === null) {
        const created = await createPersonalStyle({
          name: name.trim(),
          description: description.trim(),
          source: "photos",
          suitableScenes: [],
          targets: {},
          avoid: [],
        });
        styleId = created.style.id;
        setCreatedStyleId(styleId);
      }
      await addPersonalStyleReferences(
        styleId,
        selected.map((item) => item.id),
      );
      router.push(`/visual-dna/${encodeURIComponent(styleId)}${autoAnalyze ? "?start=1" : ""}`);
    } catch (reason: unknown) {
      setError(
        reason instanceof ApiClientError
          ? reason.message
          : "创建个人风格失败，请稍后重试。",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto w-full max-w-[1280px] px-4 py-6 sm:px-6 lg:px-8">
      <VisualDnaNav />
      <div className="mt-6 flex flex-wrap items-end justify-between gap-4 border-b border-[#e4e8e5] pb-5">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.28em] text-[#8a9a93]">
            NEW VISUAL DNA
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-[-0.045em] text-[#1d2521] sm:text-4xl">
            从参考照片创建个人风格
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-[#68746e]">
            选择一组能代表你审美的照片。系统会先分析单张照片，再找出多张照片中反复出现的共同特征。
          </p>
        </div>
        <Link
          href="/visual-dna"
          className="text-xs font-medium text-[#277a68] hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          ← 返回我的风格
        </Link>
      </div>

      <form onSubmit={(event) => void handleSubmit(event)} className="mt-6 space-y-6">
        <section className="rounded-2xl border border-[#dfe5e1] bg-white p-5 sm:p-6">
          <h2 className="text-sm font-semibold text-[#202522]">1. 命名与描述</h2>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <label className="block">
              <span className="text-xs font-medium text-[#4a574f]">风格名称</span>
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                maxLength={64}
                placeholder="例如：克制的城市叙事"
                className="mt-1.5 min-h-11 w-full rounded-xl border border-[#dfe5e1] bg-white px-3.5 text-sm text-[#2a3530] placeholder:text-[#a4aea9] focus:border-[#9dbdaf] focus:outline-none"
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-[#4a574f]">一句话描述</span>
              <input
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                maxLength={500}
                placeholder="例如：低饱和、偏冷，但保留真实的街头质感。"
                className="mt-1.5 min-h-11 w-full rounded-xl border border-[#dfe5e1] bg-white px-3.5 text-sm text-[#2a3530] placeholder:text-[#a4aea9] focus:border-[#9dbdaf] focus:outline-none"
              />
            </label>
          </div>
        </section>

        <section className="rounded-2xl border border-[#dfe5e1] bg-white p-5 sm:p-6">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-sm font-semibold text-[#202522]">2. 选择参考照片</h2>
            <p className="text-[11px] text-[#8a9690]">
              少于 {SUGGESTED_MIN} 张时，系统会主动降低风格置信度。
            </p>
          </div>
          <div className="mt-4">
            <ReferenceSelection
              selected={selected}
              onChange={setSelected}
              consent={consent}
              onConsentChange={setConsent}
            />
          </div>
        </section>

        <section className="rounded-2xl border border-[#dfe5e1] bg-white p-5 sm:p-6">
          <h2 className="text-sm font-semibold text-[#202522]">3. 创建</h2>
          <label className="mt-3 flex items-start gap-3 text-xs leading-relaxed text-[#55625b]">
            <input
              type="checkbox"
              checked={autoAnalyze}
              onChange={(event) => setAutoAnalyze(event.target.checked)}
              className="mt-0.5 size-4 accent-[#277a68]"
            />
            创建后立即分析参考照片。分析会调用当前配置的视觉模型；也可以稍后在风格工作台手动开始。
          </label>

          {error !== null && (
            <div className="mt-4">
              <MasterVisionStatus
                tone="error"
                title="创建未完成"
                action={
                  createdStyleId !== null ? (
                    <Link
                      href={`/visual-dna/${encodeURIComponent(createdStyleId)}`}
                      className="min-h-9 rounded-lg border border-[#e6bdb7] bg-white px-3 py-2 text-xs font-medium text-[#8a3a2e] hover:bg-[#fff7f5] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                    >
                      打开已创建的草稿
                    </Link>
                  ) : undefined
                }
              >
                {error}
              </MasterVisionStatus>
            </div>
          )}

          <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-[#eef1ef] pt-4">
            <p className="text-[11px] text-[#8a9690]">
              参考照片仅用于本风格分析，不用于模型训练。
            </p>
            <button
              type="submit"
              disabled={!canSubmit}
              className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-[#277a68] px-5 text-sm font-medium text-white shadow-[0_12px_30px_-18px_rgba(39,122,104,0.75)] hover:bg-[#206557] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy ? "正在创建…" : "创建个人风格"}
              <ArrowRightIcon className="size-4" />
            </button>
          </div>
        </section>
      </form>
    </main>
  );
}
