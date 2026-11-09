"use client";

import type { PersonalStyleFusionResponse } from "@/types/personal-style";

import { formatPercent, sceneLabel } from "../presentation";

export function FusionResultPanel({ fusion }: { fusion: PersonalStyleFusionResponse }) {
  return (
    <section aria-labelledby="fusion-heading" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-[#8a9a93]">
            FUSION REPORT
          </p>
          <h2 id="fusion-heading" className="mt-1 text-xl font-semibold tracking-[-0.03em] text-[#1d2521]">
            本次融合结果
          </h2>
        </div>
        <p className="text-[11px] text-[#8a9690]">
          v{fusion.version} · 置信度 {formatPercent(fusion.confidence)} · 默认强度{" "}
          {formatPercent(fusion.defaultStrength)}
        </p>
      </div>

      <div className="whitespace-pre-line rounded-xl border border-[#dfe5e1] bg-[#f9fbf9] px-4 py-3 text-xs leading-relaxed text-[#3b4841]">
        {fusion.summary}
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {fusion.sections.map((section) => (
          <div
            key={section.key}
            className="rounded-xl border border-[#dfe5e1] bg-white p-3.5"
          >
            <h3 className="text-[11px] font-semibold text-[#277a68]">{section.title}</h3>
            <p className="mt-1.5 text-[11px] leading-relaxed text-[#4a574f]">
              {section.description}
            </p>
            {section.evidence.length > 0 && (
              <ul className="mt-2 list-disc space-y-0.5 pl-4 text-[10px] leading-relaxed text-[#8a9690]">
                {section.evidence.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>

      {fusion.conflicts.length > 0 && (
        <div className="rounded-xl border border-[#efd9b5] bg-[#fdfaf3] p-4">
          <h3 className="text-xs font-semibold text-[#8a6228]">检测到偏好冲突</h3>
          <ul className="mt-2 space-y-2">
            {fusion.conflicts.map((conflict) => (
              <li
                key={conflict.dimension}
                className="rounded-lg border border-[#f0e0c5] bg-white/70 px-3 py-2 text-[11px] leading-relaxed text-[#7b6228]"
              >
                <span className="font-semibold">
                  {conflict.labels[0]} {formatPercent(conflict.support[0])} /{" "}
                  {conflict.labels[1]} {formatPercent(conflict.support[1])}
                </span>
                <p className="mt-1">{conflict.message}</p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {fusion.scenes.length > 0 && (
        <div className="rounded-xl border border-[#dfe5e1] bg-white p-4">
          <h3 className="text-xs font-semibold text-[#33413a]">场景分布</h3>
          <ul className="mt-2 grid gap-2 sm:grid-cols-2">
            {fusion.scenes.map((scene) => (
              <li
                key={scene.scene}
                className="rounded-lg border border-[#eef1ef] bg-[#f9fbf9] px-3 py-2"
              >
                <div className="flex items-center justify-between text-[11px]">
                  <span className="font-medium text-[#3b4841]">{sceneLabel(scene.scene)}</span>
                  <span className="text-[#8a9690]">
                    {scene.photoCount} 张 · {formatPercent(scene.share)}
                  </span>
                </div>
                <p className="mt-1 text-[10px] leading-relaxed text-[#7a8680]">
                  {scene.description}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {fusion.occasional.length > 0 && (
        <div className="rounded-xl border border-[#dfe5e1] bg-white p-4">
          <h3 className="text-xs font-semibold text-[#33413a]">个别特征与不稳定项</h3>
          <ul className="mt-2 list-disc space-y-1 pl-4 text-[11px] leading-relaxed text-[#7a8680]">
            {fusion.occasional.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      {fusion.limitations.length > 0 && (
        <div className="rounded-xl border border-[#e4e8e5] bg-[#f7f9f7] p-4">
          <h3 className="text-xs font-semibold text-[#55625b]">限制与注意事项</h3>
          <ul className="mt-2 list-disc space-y-1 pl-4 text-[11px] leading-relaxed text-[#7a8680]">
            {fusion.limitations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
