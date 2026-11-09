"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiClientError } from "@/lib/api/client";
import { fetchStyleLibrary, setStyleFavorite } from "@/lib/api/style-library";
import type { SceneLabel, StyleKind, StyleLibraryItem } from "@/types/style-library";

import { MasterVisionNav } from "./master-vision-nav";
import { MasterVisionStatus } from "./status";
import { StyleCard } from "./style-card";
import { SCENE_LABELS } from "../presentation";

const COPY: Record<StyleKind, { eyebrow: string; title: string; description: string }> = {
  master: {
    eyebrow: "MASTER ARCHIVE",
    title: "大师风格库",
    description: "从摄影师的思想、光影与色彩语言出发，找到与你照片对话的视觉方向。",
  },
  genre: {
    eyebrow: "GENRE ARCHIVE",
    title: "摄影流派",
    description: "不指定某一位摄影师，也可以直接使用成熟的摄影类型语言。",
  },
};

export function StyleLibraryPage({ kind }: { kind: StyleKind }) {
  const [styles, setStyles] = useState<StyleLibraryItem[] | null>(null);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const [favoriteError, setFavoriteError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [scene, setScene] = useState<SceneLabel | "">("");
  const [attempt, setAttempt] = useState(0);
  const [busyId, setBusyId] = useState<string | null>(null);
  const copy = COPY[kind];
  const key = `${kind}:${scene}:${search}:${attempt}`;

  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      fetchStyleLibrary(
        { kind, search, scene: scene === "" ? undefined : scene },
        controller.signal,
      )
        .then((response) => {
          if (!controller.signal.aborted) {
            setStyles(response.styles);
            setLoadedKey(key);
            setError(null);
            setErrorKey(null);
          }
        })
        .catch((reason: unknown) => {
          if (!controller.signal.aborted) {
            setError(
              reason instanceof ApiClientError
                ? reason.message
                : "无法连接风格库，请确认 API 服务已经启动。",
            );
            setErrorKey(key);
            setStyles(null);
            setLoadedKey(null);
          }
        });
    }, search === "" ? 0 : 220);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [key, kind, scene, search]);

  const currentStyles = loadedKey === key ? styles : null;
  const currentError = errorKey === key ? error : null;

  const toggleFavorite = useCallback((style: StyleLibraryItem) => {
    const next = !style.favorite;
    setBusyId(style.id);
    setFavoriteError(null);
    setStyles((current) =>
      current === null
        ? current
        : current.map((item) => (item.id === style.id ? { ...item, favorite: next } : item)),
    );
    setStyleFavorite(style.id, next)
      .catch((reason: unknown) => {
        setFavoriteError(
          reason instanceof ApiClientError ? reason.message : "收藏操作失败，请稍后重试。",
        );
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

  return (
    <main className="mx-auto w-full max-w-[1680px] px-4 py-6 sm:px-6 lg:px-8">
      <MasterVisionNav />
      <section className="mt-6 border-b border-[#e4e8e5] pb-5">
        <p className="text-[10px] font-semibold tracking-[0.28em] text-[#8a9a93]">
          {copy.eyebrow}
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-[-0.045em] text-[#1d2521] sm:text-4xl">
          {copy.title}
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-[#68746e]">{copy.description}</p>
      </section>

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <label className="relative min-w-0 flex-1 sm:max-w-xs">
          <span className="sr-only">搜索风格</span>
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="搜索名称或关键词"
            className="min-h-11 w-full rounded-xl border border-[#dfe5e1] bg-white px-3.5 text-sm text-[#2a3530] placeholder:text-[#9aa5a0] focus:border-[#9dbdaf] focus:outline-none"
          />
        </label>
        <label className="inline-flex items-center gap-2 text-xs text-[#7a8680]">
          适合场景
          <select
            value={scene}
            onChange={(event) => setScene(event.target.value as SceneLabel | "")}
            className="min-h-11 rounded-xl border border-[#dfe5e1] bg-white px-3 text-xs text-[#2a3530] focus:border-[#9dbdaf] focus:outline-none"
          >
            <option value="">全部</option>
            {(Object.keys(SCENE_LABELS) as SceneLabel[]).map((value) => (
              <option key={value} value={value}>
                {SCENE_LABELS[value]}
              </option>
            ))}
          </select>
        </label>
        {currentStyles !== null && (
          <p className="ml-auto text-xs text-[#8a9690]" role="status">
            {currentStyles.length} 个风格
          </p>
        )}
      </div>

      {favoriteError && (
        <div className="mt-4">
          <MasterVisionStatus tone="error" title="收藏操作未完成">
            {favoriteError}
          </MasterVisionStatus>
        </div>
      )}

      {currentError ? (
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
      ) : currentStyles === null ? (
        <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-label="正在加载风格" role="status">
          {[0, 1, 2, 3, 4, 5].map((item) => (
            <div key={item} className="animate-pulse rounded-2xl border border-[#e8ece9] bg-white">
              <div className="aspect-[16/10] rounded-t-2xl bg-[#eef2ef]" />
              <div className="space-y-3 p-4">
                <div className="h-3 w-20 rounded bg-[#eef2ef]" />
                <div className="h-5 w-36 rounded bg-[#e8edea]" />
                <div className="h-3 w-full rounded bg-[#f1f4f2]" />
              </div>
            </div>
          ))}
        </div>
      ) : currentStyles.length === 0 ? (
        <div className="mt-6 rounded-2xl border border-dashed border-[#d9e2dd] bg-[#f8faf8] px-6 py-12 text-center">
          <p className="text-sm font-medium text-[#4f5f57]">没有匹配的风格</p>
          <p className="mt-1 text-xs text-[#8a9690]">尝试清空搜索词或切换场景。</p>
        </div>
      ) : (
        <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {currentStyles.map((style) => (
            <StyleCard
              key={style.id}
              style={style}
              onToggleFavorite={toggleFavorite}
              favoriteBusy={busyId === style.id}
            />
          ))}
        </div>
      )}
    </main>
  );
}
