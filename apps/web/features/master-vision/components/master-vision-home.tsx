"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ArrowRightIcon, SparkleIcon, UploadCloudIcon } from "@/components/icons";
import { ApiClientError } from "@/lib/api/client";
import {
  fetchFavorites,
  fetchRecent,
  fetchRecommended,
  setStyleFavorite,
} from "@/lib/api/style-library";
import type {
  StyleLibraryItem,
  StyleRecentItem,
  StyleRecommendation,
} from "@/types/style-library";

import { MasterVisionNav } from "./master-vision-nav";
import { MasterVisionStatus } from "./status";
import { StyleCard } from "./style-card";

interface HomeData {
  recommended: StyleRecommendation[];
  recent: StyleRecentItem[];
  favorites: StyleLibraryItem[];
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiClientError) {
    return error.message;
  }
  return "无法连接风格库，请确认 API 服务已经启动。";
}

function updateFavorite(items: StyleLibraryItem[], styleId: string, favorite: boolean) {
  return items.map((item) => (item.id === styleId ? { ...item, favorite } : item));
}

export function MasterVisionHome() {
  const [data, setData] = useState<HomeData | null>(null);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const [favoriteError, setFavoriteError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [busyId, setBusyId] = useState<string | null>(null);
  const key = String(attempt);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      fetchRecommended({ limit: 6 }, controller.signal),
      fetchRecent(6, controller.signal),
      fetchFavorites(controller.signal),
    ])
      .then(([recommended, recent, favorites]) => {
        if (!controller.signal.aborted) {
          setData({
            recommended: recommended.styles,
            recent: recent.styles,
            favorites: favorites.styles,
          });
          setLoadedKey(key);
          setError(null);
          setErrorKey(null);
        }
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(errorMessage(reason));
          setErrorKey(key);
          setData(null);
          setLoadedKey(null);
        }
      });
    return () => controller.abort();
  }, [key]);

  const currentData = loadedKey === key ? data : null;
  const currentError = errorKey === key ? error : null;

  const toggleFavorite = useCallback(
    (style: StyleLibraryItem) => {
      if (!currentData) return;
      const next = !style.favorite;
      setBusyId(style.id);
      setFavoriteError(null);
      setData({
        recommended: currentData.recommended.map((item) => ({
          ...item,
          style: item.style.id === style.id ? { ...item.style, favorite: next } : item.style,
        })),
        recent: currentData.recent.map((item) => ({
          ...item,
          style: item.style.id === style.id ? { ...item.style, favorite: next } : item.style,
        })),
        favorites: next
          ? currentData.favorites.some((item) => item.id === style.id)
            ? currentData.favorites
            : [...currentData.favorites, { ...style, favorite: true }]
          : currentData.favorites.filter((item) => item.id !== style.id),
      });
      setStyleFavorite(style.id, next)
        .catch((reason: unknown) => {
          setFavoriteError(errorMessage(reason));
          setData((current) => {
            if (!current) return current;
            return {
              recommended: current.recommended.map((item) => ({
                ...item,
                style:
                  item.style.id === style.id
                    ? { ...item.style, favorite: style.favorite }
                    : item.style,
              })),
              recent: current.recent.map((item) => ({
                ...item,
                style:
                  item.style.id === style.id
                    ? { ...item.style, favorite: style.favorite }
                    : item.style,
              })),
              favorites: style.favorite
                ? current.favorites.some((item) => item.id === style.id)
                  ? current.favorites
                  : [...current.favorites, style]
                : updateFavorite(current.favorites, style.id, false).filter(
                    (item) => item.id !== style.id,
                  ),
            };
          });
        })
        .finally(() => setBusyId(null));
    },
    [currentData],
  );

  return (
    <div className="min-h-dvh">
      <main className="mx-auto w-full max-w-[1680px] px-4 py-6 sm:px-6 lg:px-8">
        <MasterVisionNav />
        <section className="mt-6 overflow-hidden rounded-[28px] border border-[#dfe5e1] bg-white shadow-[0_30px_80px_-60px_rgba(20,45,34,0.45)]">
          <div className="grid gap-8 px-6 py-8 sm:px-9 sm:py-11 lg:grid-cols-[1.25fr_0.75fr] lg:items-center">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.28em] text-[#78908a]">
                MASTER VISION · 大师视觉
              </p>
              <h1 className="mt-3 max-w-2xl text-4xl font-semibold leading-[1.06] tracking-[-0.05em] text-[#1d2521] sm:text-5xl">
                把大师的视觉语言，
                <br />
                带进你的照片。
              </h1>
              <p className="mt-4 max-w-xl text-sm leading-relaxed text-[#66716b]">
                从摄影师的色彩、光影与构图理念出发，而不是一套固定滤镜。选择大师或流派，让 AI 根据这张照片重新制定后期方案。
              </p>
              <div className="mt-6 flex flex-wrap gap-2.5">
                <Link
                  href="/master-vision/masters"
                  className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-[#277a68] px-5 text-sm font-medium text-[#f7faf8] shadow-[0_12px_30px_-18px_rgba(39,122,104,0.75)] transition-colors hover:bg-[#206557] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                >
                  进入大师风格库
                  <ArrowRightIcon className="size-4" />
                </Link>
                <Link
                  href="/master-vision/genres"
                  className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-[#d7dfda] bg-white px-5 text-sm font-medium text-[#415049] transition-colors hover:border-[#bfcfc6] hover:bg-[#f7faf8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                >
                  浏览摄影流派
                </Link>
                <Link
                  href="/master-vision/workspace"
                  className="inline-flex min-h-11 items-center gap-2 rounded-xl px-4 text-sm font-medium text-[#277a68] hover:bg-[#eef5f1] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                >
                  <UploadCloudIcon className="size-4" />
                  上传照片开始创作
                </Link>
              </div>
            </div>
            <div className="relative hidden min-h-64 overflow-hidden rounded-2xl border border-[rgba(255,255,255,0.14)] bg-[#101b20] lg:block">
              <div className="absolute inset-0 bg-[radial-gradient(circle_at_24%_20%,rgba(160,196,184,.58),transparent_52%),radial-gradient(circle_at_80%_72%,rgba(84,129,150,.62),transparent_58%),linear-gradient(145deg,#1b2429,#34474e)]" />
              <div className="absolute inset-0 opacity-30 [background-image:repeating-linear-gradient(105deg,rgba(255,255,255,.24)_0_1px,transparent_1px_13px)]" />
              <div className="relative flex h-full flex-col justify-end p-6">
                <SparkleIcon className="size-7 text-[#f7faf8]/80" />
                <p className="mt-3 text-sm font-medium tracking-[0.04em] text-[#f7faf8]">
                  先理解照片，再决定风格如何落地
                </p>
                <p className="mt-1.5 text-xs leading-relaxed text-[#f7faf8]/60">
                  适配度、转换模式与连续强度共同约束每一次生成。
                </p>
              </div>
            </div>
          </div>
        </section>

        {currentError && (
          <div className="mt-5">
            <MasterVisionStatus
              tone="error"
              title="风格库加载失败"
              action={
                <button
                  type="button"
                  onClick={() => setAttempt((value) => value + 1)}
                  className="min-h-9 rounded-lg border border-[#e6bdb7] bg-white px-3 text-xs font-medium text-[#8a3a2e] hover:bg-[#fff7f5] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                >
                  重新加载
                </button>
              }
            >
              {currentError}
            </MasterVisionStatus>
          </div>
        )}

        {favoriteError && (
          <div className="mt-4">
            <MasterVisionStatus tone="error" title="收藏操作未完成">
              {favoriteError}
            </MasterVisionStatus>
          </div>
        )}

        {!currentData && !currentError && <HomeSkeleton />}

        {currentData && (
          <div className="mt-8 space-y-10">
            <section aria-labelledby="recommended-heading">
              <SectionHeading
                id="recommended-heading"
                eyebrow="FOR YOU"
                title="推荐风格"
                description="从风格库中挑出的起点，完成分析后可查看照片级适配度。"
                href="/master-vision/masters"
                linkLabel="查看全部大师"
              />
              {currentData.recommended.length === 0 ? (
                <EmptyHint title="暂无推荐风格" description="启用至少一个风格档案后，这里会出现推荐。" />
              ) : (
                <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                  {currentData.recommended.map((item) => (
                    <div key={item.style.id} className="flex min-w-0 flex-col gap-2">
                      <StyleCard
                        style={item.style}
                        onToggleFavorite={toggleFavorite}
                        favoriteBusy={busyId === item.style.id}
                      />
                      <p className="px-1 text-[10px] leading-relaxed text-[#8a9690]">{item.reason}</p>
                    </div>
                  ))}
                </div>
              )}
            </section>

            <section aria-labelledby="recent-heading">
              <SectionHeading
                id="recent-heading"
                eyebrow="RECENT"
                title="最近使用"
                description="继续上一次的创作方向。"
              />
              {currentData.recent.length === 0 ? (
                <EmptyHint
                  title="还没有使用记录"
                  description="选择风格并生成方案后，会在这里快速回到最近的方向。"
                />
              ) : (
                <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                  {currentData.recent.map((item) => (
                    <div key={item.style.id} className="relative">
                      <StyleCard
                        style={item.style}
                        compact
                        onToggleFavorite={toggleFavorite}
                        favoriteBusy={busyId === item.style.id}
                      />
                    </div>
                  ))}
                </div>
              )}
            </section>

            <section aria-labelledby="favorites-heading">
              <SectionHeading
                id="favorites-heading"
                eyebrow="SAVED"
                title="收藏风格"
                description="你标记过、想反复使用的视觉语言。"
              />
              {currentData.favorites.length === 0 ? (
                <EmptyHint
                  title="还没有收藏"
                  description="在大师或流派卡片上点击心形图标，即可在这里快速找到。"
                />
              ) : (
                <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                  {currentData.favorites.map((style) => (
                    <StyleCard
                      key={style.id}
                      style={style}
                      compact
                      onToggleFavorite={toggleFavorite}
                      favoriteBusy={busyId === style.id}
                    />
                  ))}
                </div>
              )}
            </section>
          </div>
        )}
      </main>
    </div>
  );
}

function SectionHeading({
  id,
  eyebrow,
  title,
  description,
  href,
  linkLabel,
}: {
  id: string;
  eyebrow: string;
  title: string;
  description: string;
  href?: string;
  linkLabel?: string;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3 border-b border-[#e6ebe8] pb-3">
      <div>
        <p className="text-[10px] font-semibold tracking-[0.24em] text-[#8a9a93]">{eyebrow}</p>
        <h2 id={id} className="mt-1 text-xl font-semibold tracking-[-0.035em] text-[#202522]">
          {title}
        </h2>
        <p className="mt-1 text-xs text-[#7a8680]">{description}</p>
      </div>
      {href && linkLabel && (
        <Link
          href={href}
          className="inline-flex items-center gap-1 text-xs font-medium text-[#277a68] hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          {linkLabel}
          <ArrowRightIcon className="size-3" />
        </Link>
      )}
    </div>
  );
}

function EmptyHint({ title, description }: { title: string; description: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-[#d9e2dd] bg-[#f8faf8] px-5 py-8 text-center">
      <p className="text-sm font-medium text-[#4f5f57]">{title}</p>
      <p className="mt-1 text-xs text-[#8a9690]">{description}</p>
    </div>
  );
}

function HomeSkeleton() {
  return (
    <div aria-label="正在加载风格库" role="status" className="mt-8 space-y-4">
      {[0, 1, 2].map((row) => (
        <div key={row} className="animate-pulse rounded-2xl border border-[#e8ece9] bg-white p-5">
          <div className="h-3 w-24 rounded bg-[#edf1ee]" />
          <div className="mt-3 h-5 w-48 rounded bg-[#e8edea]" />
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            {[0, 1, 2].map((card) => (
              <div key={card} className="h-32 rounded-xl bg-[#f1f4f2]" />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
