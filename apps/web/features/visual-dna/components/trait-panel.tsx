"use client";

import type { PersonalStyleProfile } from "@/types/personal-style";

import {
  AVOID_LABELS,
  CONSTRAINT_LABELS,
  STABILITY_LABELS,
  TARGET_FIELDS,
  formatPercent,
  formatTargetValue,
  sceneLabel,
  targetLabel,
} from "../presentation";

function TraitRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-[#eef1ef] bg-[#f9fbf9] px-3 py-2">
      <dt className="text-[10px] font-medium text-[#8a9690]">{label}</dt>
      <dd className="mt-0.5 text-xs leading-relaxed text-[#3b4841]">{value}</dd>
    </div>
  );
}

function StabilityBar({ label, value }: { label: string; value: number }) {
  const percent = Math.round(Math.min(1, Math.max(0, value)) * 100);
  return (
    <div>
      <div className="flex items-center justify-between text-[10px] text-[#7a8680]">
        <span>{label}</span>
        <span className="font-semibold text-[#4a574f]">{percent}%</span>
      </div>
      <div
        role="meter"
        aria-label={`${label}稳定度`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        className="mt-1 h-1.5 overflow-hidden rounded-full bg-[#e8eeea]"
      >
        <div
          className="h-full rounded-full bg-[#277a68]"
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}

export function TraitPanel({ profile }: { profile: PersonalStyleProfile }) {
  const targets = Object.entries(profile.personal.targets ?? {}).sort(
    ([left], [right]) =>
      TARGET_FIELDS.findIndex((field) => field.key === left) -
      TARGET_FIELDS.findIndex((field) => field.key === right),
  );
  const stability = Object.entries(profile.personal.stability ?? {});
  const hasProfile = targets.length > 0 || profile.personal.confidence > 0;

  return (
    <section aria-labelledby="traits-heading" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-[#8a9a93]">
            STYLE DNA
          </p>
          <h2 id="traits-heading" className="mt-1 text-xl font-semibold tracking-[-0.03em] text-[#1d2521]">
            风格特征
          </h2>
        </div>
        <p className="text-[11px] text-[#8a9690]">
          置信度 {formatPercent(profile.personal.confidence)} · 样本 {profile.personal.sampleCount} 张
          {profile.personal.anomalyCount > 0 ? ` · 异常 ${profile.personal.anomalyCount} 张` : ""}
        </p>
      </div>

      {!hasProfile && (
        <div className="rounded-xl border border-dashed border-[#cfd9d3] bg-[#f8faf8] px-4 py-6 text-center text-xs text-[#7a8680]">
          还没有生成风格特征。先完成参考照片分析，再点击“生成个人风格”。
        </div>
      )}

      {hasProfile && (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <dl className="space-y-2">
              <TraitRow label="色彩倾向" value={profile.color.tendency} />
              <TraitRow label="色彩关系" value={profile.color.relationships} />
              <TraitRow label="饱和度" value={profile.color.saturation} />
            </dl>
            <dl className="space-y-2">
              <TraitRow label="整体反差" value={profile.light.contrast} />
              <TraitRow label="暗部表现" value={profile.light.shadows} />
              <TraitRow label="高光表现" value={profile.light.highlights} />
              <TraitRow label="光线表达" value={profile.light.expression} />
            </dl>
            <dl className="space-y-2">
              <TraitRow label="颗粒" value={profile.texture.grain} />
              <TraitRow label="锐度" value={profile.texture.sharpness} />
              <TraitRow label="细节" value={profile.texture.detail} />
            </dl>
            <dl className="space-y-2">
              <TraitRow label="构图空间" value={profile.composition.space} />
              <TraitRow label="几何关系" value={profile.composition.geometry} />
              <TraitRow label="主体关系" value={profile.composition.subjectRelation} />
            </dl>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-xl border border-[#dfe5e1] bg-white p-4">
              <h3 className="text-xs font-semibold text-[#33413a]">数值偏好</h3>
              {targets.length === 0 ? (
                <p className="mt-2 text-[11px] text-[#8a9690]">没有额外的数值偏好。</p>
              ) : (
                <ul className="mt-3 space-y-2">
                  {targets.map(([key, value]) => {
                    const field = TARGET_FIELDS.find((item) => item.key === key);
                    const max = field?.max ?? 100;
                    const min = field?.min ?? -100;
                    const percent = ((value - min) / (max - min)) * 100;
                    return (
                      <li key={key}>
                        <div className="flex items-center justify-between text-[11px] text-[#4a574f]">
                          <span>{targetLabel(key)}</span>
                          <span className="font-semibold">{formatTargetValue(value)}</span>
                        </div>
                        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[#edf1ee]">
                          <div
                            className={`h-full rounded-full ${value < 0 ? "bg-[#9b7a44]" : "bg-[#277a68]"}`}
                            style={{ width: `${Math.max(2, Math.min(100, percent))}%` }}
                          />
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>

            <div className="rounded-xl border border-[#dfe5e1] bg-white p-4">
              <h3 className="text-xs font-semibold text-[#33413a]">稳定程度</h3>
              <div className="mt-3 space-y-2.5">
                {stability.length === 0 ? (
                  <p className="text-[11px] text-[#8a9690]">尚未计算稳定程度。</p>
                ) : (
                  stability.map(([key, value]) => (
                    <StabilityBar
                      key={key}
                      label={STABILITY_LABELS[key] ?? key}
                      value={value}
                    />
                  ))
                )}
              </div>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-xl border border-[#dfe5e1] bg-white p-4">
              <h3 className="text-xs font-semibold text-[#33413a]">适用场景</h3>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {profile.sceneFit.suitable.map((scene) => (
                  <span
                    key={scene}
                    className="rounded-full border border-[#d7e4dc] bg-[#f0f7f4] px-2 py-0.5 text-[10px] text-[#277a68]"
                  >
                    {sceneLabel(scene)}
                  </span>
                ))}
              </div>
              <p className="mt-2 text-[11px] leading-relaxed text-[#7a8680]">
                {profile.sceneFit.suitableNotes}
              </p>
              <p className="mt-1 text-[11px] leading-relaxed text-[#9a7d52]">
                {profile.sceneFit.unsuitableNotes}
              </p>
            </div>

            <div className="rounded-xl border border-[#dfe5e1] bg-white p-4">
              <h3 className="text-xs font-semibold text-[#33413a]">处理约束</h3>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {profile.constraints.length === 0 ? (
                  <span className="text-[11px] text-[#8a9690]">暂无额外约束。</span>
                ) : (
                  profile.constraints.map((constraint) => (
                    <span
                      key={constraint}
                      className="rounded-full border border-[#e4e8e5] bg-[#f7f9f7] px-2 py-0.5 text-[10px] text-[#5f6d66]"
                    >
                      {CONSTRAINT_LABELS[constraint] ?? constraint}
                    </span>
                  ))
                )}
              </div>
              {profile.personal.avoid.length > 0 && (
                <>
                  <h4 className="mt-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-[#9a7d52]">
                    用户不希望出现
                  </h4>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {profile.personal.avoid.map((effect) => (
                      <span
                        key={effect}
                        className="rounded-full border border-[#eadfc4] bg-[#fbf7ec] px-2 py-0.5 text-[10px] text-[#7b6228]"
                      >
                        {AVOID_LABELS[effect] ?? effect}
                      </span>
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
