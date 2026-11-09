"use client";

import Link from "next/link";

import { ArrowRightIcon } from "@/components/icons";
import { StyleVisual } from "@/features/master-vision/components/style-visual";
import type { PersonalStyleItem } from "@/types/personal-style";

import {
  SOURCE_LABELS,
  STYLE_STATUS_LABELS,
  formatDateTime,
  formatPercent,
} from "../presentation";

function HeartIcon({ filled }: { filled: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      className="size-4"
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth="1.7"
    >
      <path d="M12 20.2 4.5 13a4.6 4.6 0 0 1 6.5-6.5l1 1 1-1a4.6 4.6 0 0 1 6.5 6.5Z" />
    </svg>
  );
}

export function PersonalStyleCard({
  style,
  onToggleFavorite,
  favoriteBusy = false,
}: {
  style: PersonalStyleItem;
  onToggleFavorite?: (style: PersonalStyleItem) => void;
  favoriteBusy?: boolean;
}) {
  const statusTone =
    style.status === "published"
      ? "border-[#c4ddcf] bg-[#f1f8f4] text-[#25624f]"
      : style.status === "disabled"
        ? "border-[#e4e8e5] bg-[#f7f9f7] text-[#8a9690]"
        : "border-[#eadfc4] bg-[#fbf7ec] text-[#7b6228]";

  return (
    <article className="group flex min-w-0 flex-col overflow-hidden rounded-2xl border border-[#dfe5e1] bg-white shadow-[0_18px_44px_-36px_rgba(25,48,38,0.45)] transition-shadow duration-200 hover:shadow-[0_24px_54px_-34px_rgba(25,48,38,0.5)]">
      <Link
        href={`/visual-dna/${encodeURIComponent(style.id)}`}
        className="block focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        aria-label={`打开个人风格 ${style.name}`}
      >
        <StyleVisual
          styleId={style.id}
          kind="personal"
          label="个人风格 · 示意视觉"
          className="aspect-[16/10]"
        />
      </Link>
      <div className="flex min-h-0 flex-1 flex-col gap-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#78908a]">
                {SOURCE_LABELS[style.source]} · v{style.version}
              </span>
              <span
                className={`rounded-full border px-1.5 py-0.5 text-[9px] font-medium ${statusTone}`}
              >
                {STYLE_STATUS_LABELS[style.status]}
              </span>
            </div>
            <h3 className="mt-1 truncate text-[15px] font-semibold tracking-[-0.02em] text-[#202522]">
              {style.name}
            </h3>
          </div>
          {onToggleFavorite !== undefined && (
            <button
              type="button"
              aria-label={style.favorite ? `取消收藏 ${style.name}` : `收藏 ${style.name}`}
              aria-pressed={style.favorite}
              disabled={favoriteBusy}
              onClick={() => onToggleFavorite(style)}
              className="grid size-10 shrink-0 place-items-center rounded-full border border-[#e4e8e5] text-[#8a9690] transition-colors hover:border-[#c9d4ce] hover:text-[#277a68] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent aria-pressed:border-[#bfd5ca] aria-pressed:bg-[#f0f7f4] aria-pressed:text-[#277a68] disabled:opacity-50"
            >
              <HeartIcon filled={style.favorite} />
            </button>
          )}
        </div>

        <p className="line-clamp-3 text-xs leading-relaxed text-[#66716b]">
          {style.description}
        </p>

        <dl className="grid grid-cols-3 gap-2 rounded-xl border border-[#eef1ef] bg-[#f9fbf9] px-3 py-2 text-[10px] text-[#7a8680]">
          <div>
            <dt>置信度</dt>
            <dd className="mt-0.5 text-xs font-semibold text-[#2c3a34]">
              {formatPercent(style.confidence)}
            </dd>
          </div>
          <div>
            <dt>参考照片</dt>
            <dd className="mt-0.5 text-xs font-semibold text-[#2c3a34]">
              {style.referenceCount}
            </dd>
          </div>
          <div>
            <dt>样本</dt>
            <dd className="mt-0.5 text-xs font-semibold text-[#2c3a34]">
              {style.sampleCount}
            </dd>
          </div>
        </dl>

        <div className="mt-auto flex items-end justify-between gap-3 border-t border-[#eef1ef] pt-3">
          <p className="text-[10px] text-[#8a9690]">更新于 {formatDateTime(style.updatedAt)}</p>
          <Link
            href={`/visual-dna/${encodeURIComponent(style.id)}`}
            className="inline-flex shrink-0 items-center gap-1 text-[11px] font-medium text-[#277a68] hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            打开工作台
            <ArrowRightIcon className="size-3" />
          </Link>
        </div>
      </div>
    </article>
  );
}
