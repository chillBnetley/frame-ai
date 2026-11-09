"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ArrowRightIcon } from "@/components/icons";
import { ApiClientError } from "@/lib/api/client";
import { fetchStyleDetail, setStyleFavorite } from "@/lib/api/style-library";
import type { StyleDetailResponse, StyleProfile } from "@/types/style-library";

import { MasterVisionNav } from "./master-vision-nav";
import { MasterVisionStatus } from "./status";
import { StyleVisual } from "./style-visual";
import { SCENE_LABELS, STYLE_KIND_LABELS, sceneLabel } from "../presentation";

function HeartIcon({ filled }: { filled: boolean }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="size-4" fill={filled ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.7">
      <path d="M12 20.2 4.5 13a4.6 4.6 0 0 1 6.5-6.5l1 1 1-1a4.6 4.6 0 0 1 6.5 6.5Z" />
    </svg>
  );
}

export function StyleDetailView({ styleId }: { styleId: string }) {
  const [data, setData] = useState<StyleDetailResponse | null>(null);
  const [dataKey, setDataKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [favoriteBusy, setFavoriteBusy] = useState(false);
  const [favoriteError, setFavoriteError] = useState<string | null>(null);
  const key = `${styleId}:${attempt}`;

  useEffect(() => {
    const controller = new AbortController();
    fetchStyleDetail(styleId, controller.signal)
      .then((response) => {
        if (!controller.signal.aborted) {
          setData(response);
          setDataKey(key);
          setError(null);
          setErrorKey(null);
        }
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(
            reason instanceof ApiClientError
              ? reason.message
              : "无法加载风格详情，请确认 API 服务已经启动。",
          );
          setErrorKey(key);
          setData(null);
          setDataKey(null);
        }
      });
    return () => controller.abort();
  }, [attempt, key, styleId]);

  const detail = dataKey === key ? data : null;
  const currentError = errorKey === key ? error : null;

  const toggleFavorite = useCallback(() => {
    if (!data) return;
    const next = !data.favorite;
    setFavoriteBusy(true);
    setFavoriteError(null);
    setData({ ...data, favorite: next });
    setStyleFavorite(styleId, next)
      .catch((reason: unknown) => {
        setFavoriteError(
          reason instanceof ApiClientError ? reason.message : "收藏操作失败，请稍后重试。",
        );
        setData((current) => (current ? { ...current, favorite: !next } : current));
      })
      .finally(() => setFavoriteBusy(false));
  }, [data, styleId]);

  return (
    <main className="mx-auto w-full max-w-[1680px] px-4 py-6 sm:px-6 lg:px-8">
      <MasterVisionNav />
      {currentError ? (
        <div className="mt-6">
          <MasterVisionStatus
            tone="error"
            title="风格详情加载失败"
            action={
              <button
                type="button"
                onClick={() => setAttempt((value) => value + 1)}
                className="min-h-9 rounded-lg border border-[#e6bdb7] bg-white px-3 text-xs font-medium text-[#8a3a2e] hover:bg-[#fff7f5] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                重试
              </button>
            }
          >
            {currentError}
          </MasterVisionStatus>
        </div>
      ) : detail === null ? (
        <div className="mt-6 animate-pulse space-y-4" role="status" aria-label="正在加载风格详情">
          <div className="h-64 rounded-3xl bg-[#eef2ef]" />
          <div className="h-6 w-64 rounded bg-[#e8edea]" />
          <div className="h-24 rounded-2xl bg-[#f1f4f2]" />
        </div>
      ) : (
        <StyleDetailContent
          profile={detail.style}
          favorite={detail.favorite}
          favoriteBusy={favoriteBusy}
          favoriteError={favoriteError}
          onToggleFavorite={toggleFavorite}
        />
      )}
    </main>
  );
}

function StyleDetailContent({
  profile,
  favorite,
  favoriteBusy,
  favoriteError,
  onToggleFavorite,
}: {
  profile: StyleProfile;
  favorite: boolean;
  favoriteBusy: boolean;
  favoriteError: string | null;
  onToggleFavorite: () => void;
}) {
  const backHref = profile.kind === "master" ? "/master-vision/masters" : "/master-vision/genres";
  return (
    <>
      <div className="mt-4">
        <Link
          href={backHref}
          className="inline-flex items-center gap-1 text-xs text-[#7a8680] hover:text-[#277a68] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          ← 返回{STYLE_KIND_LABELS[profile.kind]}库
        </Link>
      </div>

      <section className="mt-4 grid gap-6 lg:grid-cols-[1.05fr_0.95fr] lg:items-stretch">
        <StyleVisual styleId={profile.id} kind={profile.kind} className="min-h-72 rounded-3xl" />
        <div className="flex flex-col justify-center rounded-3xl border border-[#dfe5e1] bg-white p-6 shadow-[0_24px_60px_-48px_rgba(25,48,38,0.5)] sm:p-8">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-[#eef5f1] px-2.5 py-1 text-[10px] font-semibold tracking-[0.12em] text-[#277a68]">
              {STYLE_KIND_LABELS[profile.kind]}
            </span>
            <span className="font-mono text-[10px] text-[#98a39e]">v{profile.version}</span>
            <span className="text-[10px] text-[#98a39e]">引擎：{profile.engineStyle}</span>
          </div>
          <h1 className="mt-3 text-3xl font-semibold tracking-[-0.045em] text-[#1d2521] sm:text-4xl">
            {profile.name}
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-[#616d67]">{profile.description}</p>
          <blockquote className="mt-5 border-l-2 border-[#bfd5ca] pl-4 text-sm leading-relaxed text-[#43534b]">
            {profile.philosophy}
          </blockquote>
          {favoriteError && (
            <p className="mt-4 text-xs text-[#8a3a2e]" role="alert">
              {favoriteError}
            </p>
          )}
          <div className="mt-6 flex flex-wrap gap-2.5">
            <Link
              href={`/master-vision/workspace?style=${encodeURIComponent(profile.id)}`}
              className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-[#277a68] px-5 text-sm font-medium text-[#f7faf8] shadow-[0_12px_30px_-18px_rgba(39,122,104,0.75)] hover:bg-[#206557] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              开始创作
              <ArrowRightIcon className="size-4" />
            </Link>
            <button
              type="button"
              disabled={favoriteBusy}
              aria-pressed={favorite}
              onClick={onToggleFavorite}
              className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-[#d7dfda] bg-white px-4 text-sm text-[#4d5c54] hover:border-[#bfcfc6] hover:bg-[#f7faf8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent aria-pressed:border-[#bfd5ca] aria-pressed:bg-[#f0f7f4] aria-pressed:text-[#277a68] disabled:opacity-60"
            >
              <HeartIcon filled={favorite} />
              {favorite ? "已收藏" : "收藏风格"}
            </button>
          </div>
        </div>
      </section>

      <section aria-labelledby="trait-heading" className="mt-9">
        <SectionTitle
          id="trait-heading"
          eyebrow="WHY IT LOOKS THIS WAY"
          title="视觉语言如何形成画面"
          description="不是一段描述，而是可以逐项理解的色彩、光线、构图与质感选择。"
        />
        <div className="grid gap-4 md:grid-cols-2">
          <TraitCard
            title="色彩"
            items={[
              ["倾向", profile.color.tendency],
              ["关系", profile.color.relationships],
              ["饱和", profile.color.saturation],
            ]}
          />
          <TraitCard
            title="光线"
            items={[
              ["对比", profile.light.contrast],
              ["阴影", profile.light.shadows],
              ["高光", profile.light.highlights],
              ["光线表达", profile.light.expression],
            ]}
          />
          <TraitCard
            title="构图"
            items={[
              ["空间", profile.composition.space],
              ["几何", profile.composition.geometry],
              ["留白", profile.composition.negativeSpace],
              ["主体关系", profile.composition.subjectRelation],
            ]}
          />
          <TraitCard
            title="质感"
            items={[
              ["颗粒", profile.texture.grain],
              ["锐度", profile.texture.sharpness],
              ["细节", profile.texture.detail],
            ]}
          />
        </div>
      </section>

      <section aria-labelledby="fit-heading" className="mt-9 grid gap-4 lg:grid-cols-2">
        <div className="rounded-2xl border border-[#d7e3dc] bg-[#f6faf8] p-5">
          <h2 id="fit-heading" className="text-sm font-semibold text-[#2e4a40]">
            适合的场景
          </h2>
          <ul className="mt-3 flex flex-wrap gap-2">
            {profile.sceneFit.suitable.map((scene) => (
              <li
                key={scene}
                className="rounded-full border border-[#cfe0d6] bg-white px-3 py-1 text-xs text-[#3f5d50]"
              >
                {sceneLabel(scene) || SCENE_LABELS[scene]}
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs leading-relaxed text-[#5c7066]">
            {profile.sceneFit.suitableNotes}
          </p>
        </div>
        <div className="rounded-2xl border border-[#eadfd6] bg-[#fdf9f6] p-5">
          <h2 className="text-sm font-semibold text-[#6b4d3a]">不适用的场景</h2>
          <p className="mt-3 text-xs leading-relaxed text-[#7a6254]">
            {profile.sceneFit.unsuitableNotes}
          </p>
        </div>
      </section>

      <section aria-labelledby="method-heading" className="mt-9">
        <SectionTitle
          id="method-heading"
          eyebrow="POST & CAPTURE"
          title="后期与拍摄边界"
          description="哪些来自后期，哪些必须来自拍摄现场。"
        />
        <div className="grid gap-4 md:grid-cols-3">
          <NarrativeCard title="后期策略" body={profile.postStrategy} />
          <NarrativeCard title="保护原则" body={profile.preserveNotes} />
          <NarrativeCard title="拍摄技法与边界" body={profile.captureTechniques} />
        </div>
      </section>

      <section aria-labelledby="source-heading" className="mt-9">
        <SectionTitle id="source-heading" eyebrow="SOURCES" title="档案来源" description="风格研究整理；不复制或再分发受版权保护的原作。" />
        <ul className="space-y-2">
          {profile.sources.map((source) => (
            <li key={source.title} className="rounded-xl border border-[#e4e8e5] bg-white px-4 py-3 text-xs text-[#66716b]">
              <span className="font-medium text-[#46554d]">{source.title}</span>
              <span className="mt-0.5 block text-[10px] text-[#98a39e]">{source.license}</span>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}

function SectionTitle({
  id,
  eyebrow,
  title,
  description,
}: {
  id: string;
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <div className="mb-4 border-b border-[#e6ebe8] pb-3">
      <p className="text-[10px] font-semibold tracking-[0.24em] text-[#8a9a93]">{eyebrow}</p>
      <h2 id={id} className="mt-1 text-xl font-semibold tracking-[-0.035em] text-[#202522]">
        {title}
      </h2>
      <p className="mt-1 text-xs text-[#7a8680]">{description}</p>
    </div>
  );
}

function TraitCard({ title, items }: { title: string; items: Array<[string, string]> }) {
  return (
    <div className="rounded-2xl border border-[#e0e6e2] bg-white p-5">
      <h3 className="text-sm font-semibold text-[#2d3b34]">{title}</h3>
      <dl className="mt-3 space-y-3">
        {items.map(([label, value]) => (
          <div key={label} className="grid grid-cols-[4rem_1fr] gap-2">
            <dt className="text-[10px] font-medium uppercase tracking-[0.12em] text-[#98a39e]">
              {label}
            </dt>
            <dd className="text-xs leading-relaxed text-[#5f6d66]">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function NarrativeCard({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-2xl border border-[#e4e8e5] bg-[#fafbfa] p-5">
      <h3 className="text-xs font-semibold tracking-[0.06em] text-[#4c5e55]">{title}</h3>
      <p className="mt-2 text-xs leading-relaxed text-[#66716b]">{body}</p>
    </div>
  );
}
