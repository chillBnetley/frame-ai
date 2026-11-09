import Link from "next/link";

import { ArrowRightIcon } from "@/components/icons";
import type { StyleLibraryItem } from "@/types/style-library";

import { STYLE_KIND_LABELS, styleScenes } from "../presentation";
import { StyleVisual } from "./style-visual";

function HeartIcon({ filled }: { filled: boolean }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="size-4" fill={filled ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.7">
      <path d="M12 20.2 4.5 13a4.6 4.6 0 0 1 6.5-6.5l1 1 1-1a4.6 4.6 0 0 1 6.5 6.5Z" />
    </svg>
  );
}

export interface StyleCardProps {
  style: StyleLibraryItem;
  onToggleFavorite?: (style: StyleLibraryItem) => void;
  favoriteBusy?: boolean;
  compact?: boolean;
}

export function StyleCard({
  style,
  onToggleFavorite,
  favoriteBusy = false,
  compact = false,
}: StyleCardProps) {
  return (
    <article className="group flex min-w-0 flex-col overflow-hidden rounded-2xl border border-[#dfe5e1] bg-white shadow-[0_18px_44px_-36px_rgba(25,48,38,0.45)] transition-shadow duration-200 hover:shadow-[0_24px_54px_-34px_rgba(25,48,38,0.5)]">
      <Link
        href={`/master-vision/styles/${encodeURIComponent(style.id)}`}
        className="block focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        aria-label={`查看 ${style.name} 详情`}
      >
        <StyleVisual
          styleId={style.id}
          kind={style.kind}
          className={compact ? "aspect-[16/9]" : "aspect-[16/10]"}
        />
      </Link>
      <div className="flex min-h-0 flex-1 flex-col gap-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#78908a]">
              {STYLE_KIND_LABELS[style.kind]} · v{style.version}
            </p>
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

        <p className="line-clamp-3 text-xs leading-relaxed text-[#66716b]">{style.description}</p>

        {style.signature.length > 0 && (
          <ul className="flex flex-wrap gap-1.5" aria-label="代表视觉特征">
            {style.signature.slice(0, compact ? 2 : 3).map((item) => (
              <li
                key={item}
                className="rounded-full border border-[#e4e8e5] bg-[#f7f9f7] px-2 py-0.5 text-[10px] text-[#5f6d66]"
              >
                {item}
              </li>
            ))}
          </ul>
        )}

        <div className="mt-auto flex items-end justify-between gap-3 border-t border-[#eef1ef] pt-3">
          <p className="min-w-0 text-[10px] leading-relaxed text-[#8a9690]">
            <span className="font-medium text-[#6b7a73]">适合</span> {styleScenes(style)}
          </p>
          <Link
            href={`/master-vision/styles/${encodeURIComponent(style.id)}`}
            className="inline-flex shrink-0 items-center gap-1 text-[11px] font-medium text-[#277a68] hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            查看详情
            <ArrowRightIcon className="size-3" />
          </Link>
        </div>
      </div>
    </article>
  );
}
