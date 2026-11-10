"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ArrowRightIcon, SparkleIcon, UploadCloudIcon } from "@/components/icons";
import { MasterVisionStatus } from "@/features/master-vision/components/status";
import { ApiClientError } from "@/lib/api/client";
import {
  listPersonalStyles,
  setPersonalStyleFavorite,
} from "@/lib/api/personal-style";
import type { PersonalStyleItem } from "@/types/personal-style";

import { PersonalStyleCard } from "./personal-style-card";
import { VisualDnaNav } from "./visual-dna-nav";

function errorMessage(error: unknown): string {
  if (error instanceof ApiClientError) {
    return error.message;
  }
  return "无法连接个人风格库，请确认 API 服务已经启动。";
}

export function VisualDnaHome() {
  const [styles, setStyles] = useState<PersonalStyleItem[] | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [favoriteError, setFavoriteError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    listPersonalStyles({}, controller.signal)
      .then((response) => {
        if (!controller.signal.aborted) {
          setStyles(response.styles);
          setLoaded(true);
          setError(null);
        }
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(errorMessage(reason));
          setStyles(null);
          setLoaded(false);
        }
      });
    return () => controller.abort();
  }, [attempt]);

  const toggleFavorite = useCallback((style: PersonalStyleItem) => {
    const next = !style.favorite;
    setBusyId(style.id);
    setFavoriteError(null);
    setStyles((current) =>
      current === null
        ? current
        : current.map((item) => (item.id === style.id ? { ...item, favorite: next } : item)),
    );
    setPersonalStyleFavorite(style.id, next)
      .catch((reason: unknown) => {
        setFavoriteError(errorMessage(reason));
        setStyles((current) =>
          current === null
            ? current
            : current.map((item) =>
                item.id === style.id ? { ...item, favorite: style.favorite } : item,
              ),
        );
      })
      .finally(() => setBusyId(null));
  }, []);

  const currentStyles = loaded ? styles : null;

  return (
    <main className="mx-auto w-full max-w-[1680px] px-4 py-6 sm:px-6 lg:px-8">
      <VisualDnaNav />
      <section className="mt-6 overflow-hidden rounded-[28px] border border-[#dfe5e1] bg-white shadow-[0_30px_80px_-60px_rgba(20,45,34,0.45)]">
        <div className="grid gap-8 px-6 py-8 sm:px-9 sm:py-11 lg:grid-cols-[1.25fr_0.75fr] lg:items-center">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.28em] text-[#78908a]">
              VISUAL DNA · 个人视觉风格
            </p>
            <h1 className="mt-3 max-w-2xl text-4xl font-semibold leading-[1.06] tracking-[-0.05em] text-[#1d2521] sm:text-5xl">
              从你自己的照片里，
              <br />
              找到稳定的视觉偏好。
            </h1>
            <p className="mt-4 max-w-xl text-sm leading-relaxed text-[#66716b]">
              选择一组你认可的参考照片。系统会区分为单张偶然特征与多张照片反复出现的稳定偏好，
              生成一份可理解、可修改、可重复使用的个人风格。
            </p>
            <div className="mt-6 flex flex-wrap gap-2.5">
              <Link
                href="/visual-dna/new"
                className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-[#277a68] px-5 text-sm font-medium text-[#f7faf8] shadow-[0_12px_30px_-18px_rgba(39,122,104,0.75)] transition-colors hover:bg-[#206557] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                从参考照片创建
                <ArrowRightIcon className="size-4" />
              </Link>
              <Link
                href="/visual-dna/custom"
                className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-[#d7dfda] bg-white px-5 text-sm font-medium text-[#415049] transition-colors hover:border-[#bfcfc6] hover:bg-[#f7faf8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                <SparkleIcon className="size-4" />
                用自然语言创建
              </Link>
              <Link
                href="/master-vision/workspace"
                className="inline-flex min-h-11 items-center gap-2 rounded-xl px-4 text-sm font-medium text-[#277a68] hover:bg-[#eef5f1] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                <UploadCloudIcon className="size-4" />
                去大师风格工作台
              </Link>
            </div>
            <p className="mt-4 text-[11px] leading-relaxed text-[#8a9690]">
              参考照片仅在你主动授权后用于本风格分析，不用于模型训练，也不会自动公开。
            </p>
          </div>
          <div className="relative hidden min-h-64 overflow-hidden rounded-2xl border border-[rgba(255,255,255,0.14)] bg-[#101b20] lg:block">
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_22%_18%,rgba(187,208,197,.5),transparent_52%),radial-gradient(circle_at_82%_74%,rgba(168,139,92,.5),transparent_58%),linear-gradient(145deg,#1d2721,#3b4a3f)]" />
            <div className="absolute inset-0 opacity-30 [background-image:repeating-linear-gradient(112deg,rgba(255,255,255,.22)_0_1px,transparent_1px_12px)]" />
            <div className="relative flex h-full flex-col justify-end p-6">
              <SparkleIcon className="size-7 text-[#f7faf8]/80" />
              <p className="mt-3 text-sm font-medium tracking-[0.04em] text-[#f7faf8]">
                个人风格不是固定滤镜
              </p>
              <p className="mt-1.5 text-xs leading-relaxed text-[#f7faf8]/60">
                稳定偏好、场景差异与冲突会被分别记录，再进入动态适配。
              </p>
            </div>
          </div>
        </div>
      </section>

      {error !== null && (
        <div className="mt-5">
          <MasterVisionStatus
            tone="error"
            title="个人风格加载失败"
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
            {error}
          </MasterVisionStatus>
        </div>
      )}

      {favoriteError !== null && (
        <div className="mt-4">
          <MasterVisionStatus tone="error" title="收藏操作未完成">
            {favoriteError}
          </MasterVisionStatus>
        </div>
      )}

      <section aria-labelledby="personal-styles-heading" className="mt-8">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-[#8a9a93]">
              MY VISUAL DNA
            </p>
            <h2
              id="personal-styles-heading"
              className="mt-1.5 text-2xl font-semibold tracking-[-0.04em] text-[#1d2521]"
            >
              我的个人风格
            </h2>
          </div>
          {currentStyles !== null && currentStyles.length > 0 && (
            <Link
              href="/visual-dna/new"
              className="inline-flex min-h-10 items-center gap-1.5 rounded-xl border border-[#d7dfda] bg-white px-4 text-xs font-medium text-[#277a68] hover:bg-[#f4f8f6] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              新建风格
              <ArrowRightIcon className="size-3.5" />
            </Link>
          )}
        </div>

        {currentStyles === null && error === null && (
          <div className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-hidden="true">
            {[0, 1, 2].map((index) => (
              <div
                key={index}
                className="h-72 animate-pulse rounded-2xl border border-[#e4e8e5] bg-[#f4f7f5]"
              />
            ))}
          </div>
        )}

        {currentStyles !== null && currentStyles.length === 0 && (
          <div className="mt-5 rounded-2xl border border-dashed border-[#cfd9d3] bg-[#f8faf8] px-6 py-12 text-center">
            <p className="text-sm font-medium text-[#33413a]">还没有个人风格</p>
            <p className="mx-auto mt-2 max-w-md text-xs leading-relaxed text-[#7a8680]">
              选择 5–12 张你认可的摄影作品，系统会分析色彩、影调、光线与质感的共同倾向。
            </p>
            <Link
              href="/visual-dna/new"
              className="mt-5 inline-flex min-h-10 items-center gap-1.5 rounded-xl bg-[#277a68] px-4 text-xs font-medium text-white hover:bg-[#206557] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              创建第一个个人风格
              <ArrowRightIcon className="size-3.5" />
            </Link>
          </div>
        )}

        {currentStyles !== null && currentStyles.length > 0 && (
          <div className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {currentStyles.map((style) => (
              <PersonalStyleCard
                key={style.id}
                style={style}
                onToggleFavorite={toggleFavorite}
                favoriteBusy={busyId === style.id}
              />
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
