"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  AlertTriangleIcon,
  ArrowRightIcon,
  ShieldCheckIcon,
  SparkleIcon,
} from "@/components/icons";
import { MasterVisionStatus } from "@/features/master-vision/components/status";
import { ApiClientError } from "@/lib/api/client";
import { fetchPersonalStyle, listPersonalStyles } from "@/lib/api/personal-style";
import { previewStyleMix, saveStyleMix } from "@/lib/api/style-mix";
import { fetchStyleDetail, fetchStyleLibrary } from "@/lib/api/style-library";
import type { PersonalStyleProfile } from "@/types/personal-style";
import type { StyleProfile } from "@/types/style-library";
import type {
  ConflictResolution,
  MixDimension,
  MixSource,
  StyleMixPreviewResponse,
  StyleMixSourceRef,
} from "@/types/style-mix";

import { VisualDnaNav } from "./visual-dna-nav";
import { SOURCE_LABELS, formatTargetValue, targetLabel } from "../presentation";

const DIMENSIONS: Array<{ key: MixDimension; label: string }> = [
  { key: "color", label: "色彩" },
  { key: "tone", label: "影调" },
  { key: "light", label: "光线" },
  { key: "texture", label: "质感" },
  { key: "composition", label: "构图" },
  { key: "scene", label: "场景适配" },
];

const SOURCE_OPTIONS: Array<{ value: MixSource; label: string }> = [
  { value: "blend", label: "融合" },
  { value: "a", label: "风格 A" },
  { value: "b", label: "风格 B" },
];

const RESOLUTION_OPTIONS: Array<{ value: ConflictResolution; label: string }> = [
  { value: "auto", label: "自动" },
  { value: "a", label: "以 A 为准" },
  { value: "b", label: "以 B 为准" },
  { value: "neutral", label: "中性保护" },
];

const RESOLVED_BY_LABELS: Record<string, string> = {
  weight: "权重倾向",
  source: "维度来源",
  protection: "保护优先",
  user: "用户选择",
};

interface StyleOption {
  id: string;
  name: string;
  description: string;
  group: "master" | "personal";
  version: string;
  sourceLabel: string;
}

type StyleTraits = Pick<StyleProfile, "color" | "light" | "texture" | "composition">;

function errorMessage(reason: unknown, fallback: string): string {
  return reason instanceof ApiClientError ? reason.message : fallback;
}

export function VisualDnaMix() {
  const router = useRouter();
  const [options, setOptions] = useState<StyleOption[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  const [styleAId, setStyleAId] = useState("");
  const [styleBId, setStyleBId] = useState("");
  const [weight, setWeight] = useState(50);
  const [sources, setSources] = useState<Record<string, MixSource>>({});
  const [resolutions, setResolutions] = useState<Record<string, ConflictResolution>>({});

  const [preview, setPreview] = useState<StyleMixPreviewResponse | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const previewController = useRef<AbortController | null>(null);

  const [detailA, setDetailA] = useState<{ id: string; traits: StyleTraits } | null>(null);
  const [detailB, setDetailB] = useState<{ id: string; traits: StyleTraits } | null>(null);

  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      fetchStyleLibrary({}, controller.signal),
      listPersonalStyles({}, controller.signal),
    ])
      .then(([library, personal]) => {
        if (controller.signal.aborted) return;
        const masters: StyleOption[] = library.styles.map((style) => ({
          id: style.id,
          name: style.name,
          description: style.description,
          group: "master",
          version: style.version,
          sourceLabel: style.kind === "master" ? "大师风格" : "流派风格",
        }));
        const personals: StyleOption[] = personal.styles.map((style) => ({
          id: style.id,
          name: style.name,
          description: style.description,
          group: "personal",
          version: style.version,
          sourceLabel: SOURCE_LABELS[style.source],
        }));
        setOptions([...masters, ...personals]);
        setLoadError(null);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setLoadError(errorMessage(reason, "无法加载风格库，请确认 API 服务已经启动。"));
        }
      });
    return () => controller.abort();
  }, [attempt]);

  const optionA = useMemo(
    () => options?.find((option) => option.id === styleAId) ?? null,
    [options, styleAId],
  );
  const optionB = useMemo(
    () => options?.find((option) => option.id === styleBId) ?? null,
    [options, styleBId],
  );

  const sameStyle =
    styleAId !== "" &&
    styleBId !== "" &&
    styleAId === styleBId &&
    (optionA?.version ?? "") === (optionB?.version ?? "");

  const refA = useMemo<StyleMixSourceRef | null>(
    () => (optionA ? { styleId: optionA.id, version: optionA.version } : null),
    [optionA],
  );
  const refB = useMemo<StyleMixSourceRef | null>(
    () => (optionB ? { styleId: optionB.id, version: optionB.version } : null),
    [optionB],
  );

  useEffect(() => {
    if (!refA || !refB || sameStyle) return;
    const controller = new AbortController();
    previewController.current?.abort();
    previewController.current = controller;
    const timer = setTimeout(() => {
      setPreviewing(true);
      setPreviewError(null);
      previewStyleMix(
        { styleA: refA, styleB: refB, weight, sources, resolutions },
        controller.signal,
      )
        .then((response) => {
          if (controller.signal.aborted) return;
          setPreview(response);
          setName((current) => current || response.profile.name);
        })
        .catch((reason: unknown) => {
          if (controller.signal.aborted) return;
          setPreview(null);
          setPreviewError(errorMessage(reason, "无法生成混合预览，请稍后重试。"));
        })
        .finally(() => {
          if (!controller.signal.aborted) setPreviewing(false);
        });
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [refA, refB, weight, sources, resolutions, sameStyle]);

  useEffect(() => {
    if (!optionA) return;
    const controller = new AbortController();
    const load =
      optionA.group === "personal"
        ? fetchPersonalStyle(optionA.id, { signal: controller.signal }).then(
            (response) => response.style,
          )
        : fetchStyleDetail(optionA.id, controller.signal).then((response) => response.style);
    load
      .then((profile) => {
        if (!controller.signal.aborted) setDetailA({ id: optionA.id, traits: profile });
      })
      .catch(() => {
        if (!controller.signal.aborted) setDetailA(null);
      });
    return () => controller.abort();
  }, [optionA]);

  useEffect(() => {
    if (!optionB) return;
    const controller = new AbortController();
    const load =
      optionB.group === "personal"
        ? fetchPersonalStyle(optionB.id, { signal: controller.signal }).then(
            (response) => response.style,
          )
        : fetchStyleDetail(optionB.id, controller.signal).then((response) => response.style);
    load
      .then((profile) => {
        if (!controller.signal.aborted) setDetailB({ id: optionB.id, traits: profile });
      })
      .catch(() => {
        if (!controller.signal.aborted) setDetailB(null);
      });
    return () => controller.abort();
  }, [optionB]);

  const traitsA = detailA !== null && detailA.id === styleAId ? detailA.traits : null;
  const traitsB = detailB !== null && detailB.id === styleBId ? detailB.traits : null;

  const setDimensionSource = useCallback((dimension: MixDimension, source: MixSource) => {
    setSources((current) => ({ ...current, [dimension]: source }));
  }, []);

  const setConflictResolution = useCallback(
    (dimension: string, resolution: ConflictResolution) => {
      setResolutions((current) => ({ ...current, [dimension]: resolution }));
    },
    [],
  );

  async function handleSave() {
    if (!refA || !refB || preview === null || saving) return;
    const trimmed = name.trim();
    if (trimmed === "") {
      setSaveError("请填写混合风格的名称。");
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const saved = await saveStyleMix({
        styleA: refA,
        styleB: refB,
        weight,
        sources,
        resolutions,
        name: trimmed,
        note: "由风格混合工作台创建并确认。",
      });
      router.push(`/visual-dna/${encodeURIComponent(saved.style.id)}`);
    } catch (reason: unknown) {
      setSaveError(errorMessage(reason, "保存混合风格失败，请稍后重试。"));
      setSaving(false);
    }
  }

  const canSave =
    preview !== null && name.trim().length > 0 && !saving && !previewing;

  return (
    <main className="mx-auto w-full max-w-[1280px] px-4 py-6 sm:px-6 lg:px-8">
      <VisualDnaNav />
      <div className="mt-6 flex flex-wrap items-end justify-between gap-4 border-b border-[#e4e8e5] pb-5">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.28em] text-[#8a9a93]">
            STYLE MIXING
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-[-0.045em] text-[#1d2521] sm:text-4xl">
            混合两种风格
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-[#68746e]">
            选择两种风格，按维度指定特征来源并调整权重。冲突会被识别并按优先级处理，
            保护约束取并集而不被平均；混合结果可保存为独立的个人风格。
          </p>
        </div>
        <Link
          href="/visual-dna"
          className="text-xs font-medium text-[#277a68] hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          ← 返回我的风格
        </Link>
      </div>

      {loadError !== null && (
        <div className="mt-5">
          <MasterVisionStatus
            tone="error"
            title="风格库加载失败"
            action={
              <button
                type="button"
                onClick={() => {
                  setLoadError(null);
                  setAttempt((value) => value + 1);
                }}
                className="min-h-9 rounded-lg border border-[#e6bdb7] bg-white px-3 text-xs font-medium text-[#8a3a2e] hover:bg-[#fff7f5] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                重新加载
              </button>
            }
          >
            {loadError}
          </MasterVisionStatus>
        </div>
      )}

      <section className="mt-6 grid gap-4 lg:grid-cols-2">
        <StylePicker
          label="风格 A"
          value={styleAId}
          options={options}
          excludedId={styleBId}
          onChange={(id) => {
            setStyleAId(id);
            setPreview(null);
          }}
        />
        <StylePicker
          label="风格 B"
          value={styleBId}
          options={options}
          excludedId={styleAId}
          onChange={(id) => {
            setStyleBId(id);
            setPreview(null);
          }}
        />
      </section>

      {sameStyle && (
        <div className="mt-4">
          <MasterVisionStatus tone="error" title="需要两种不同的风格">
            风格 A 与风格 B 不能是同一个风格的同一版本。
          </MasterVisionStatus>
        </div>
      )}

      {optionA !== null && optionB !== null && !sameStyle && (
        <>
          <section className="mt-5 rounded-2xl border border-[#dfe5e1] bg-white p-5 sm:p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold text-[#202522]">混合权重</h2>
                <p className="mt-1 text-[11px] text-[#8a9690]">
                  权重只影响可连续插值的特征；冲突维度与保护约束不按权重平均。
                </p>
              </div>
              <p className="text-xs font-medium text-[#415049]">
                A {weight}% · B {100 - weight}%
              </p>
            </div>
            <input
              type="range"
              min={0}
              max={100}
              step={1}
              value={weight}
              aria-label="混合权重"
              onChange={(event) => setWeight(Number(event.target.value))}
              className="mt-4 w-full accent-[#277a68]"
            />
            <div className="mt-1 flex justify-between text-[10px] text-[#9aa5a0]">
              <span>完全 A</span>
              <span>均衡</span>
              <span>完全 B</span>
            </div>
          </section>

          <section className="mt-5 rounded-2xl border border-[#dfe5e1] bg-white p-5 sm:p-6">
            <h2 className="text-sm font-semibold text-[#202522]">维度特征来源</h2>
            <p className="mt-1 text-[11px] text-[#8a9690]">
              为每个维度选择特征来自哪一方，或按权重融合。
            </p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {DIMENSIONS.map((dimension) => (
                <label key={dimension.key} className="block">
                  <span className="text-xs font-medium text-[#4a574f]">{dimension.label}</span>
                  <select
                    aria-label={`${dimension.label}来源`}
                    value={sources[dimension.key] ?? "blend"}
                    onChange={(event) =>
                      setDimensionSource(dimension.key, event.target.value as MixSource)
                    }
                    className="mt-1.5 min-h-11 w-full rounded-xl border border-[#dfe5e1] bg-white px-3 text-sm text-[#2a3530] focus:border-[#9dbdaf] focus:outline-none"
                  >
                    {SOURCE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
          </section>

          {previewError !== null && (
            <div className="mt-5">
              <MasterVisionStatus tone="error" title="预览未完成">
                {previewError}
              </MasterVisionStatus>
            </div>
          )}

          {preview !== null && (
            <section aria-labelledby="mix-preview-heading" className="mt-8 space-y-5">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-[#8a9a93]">
                    MIX PREVIEW
                  </p>
                  <h2
                    id="mix-preview-heading"
                    className="mt-1 text-2xl font-semibold tracking-[-0.04em] text-[#1d2521]"
                  >
                    混合预览
                  </h2>
                </div>
                {previewing && (
                  <p className="text-[11px] text-[#8a9690]">正在更新预览…</p>
                )}
              </div>

              <div className="whitespace-pre-line rounded-xl border border-[#dfe5e1] bg-[#f9fbf9] px-4 py-3 text-xs leading-relaxed text-[#3b4841]">
                {preview.summary}
              </div>

              {preview.conflicts.length > 0 && (
                <div className="rounded-xl border border-[#efd9b5] bg-[#fdfaf3] p-4">
                  <div className="flex items-center gap-2">
                    <AlertTriangleIcon className="size-4 text-[#8a6228]" />
                    <h3 className="text-xs font-semibold text-[#8a6228]">
                      检测到 {preview.conflicts.length} 处风格冲突
                    </h3>
                  </div>
                  <div className="mt-3 space-y-3">
                    {preview.conflicts.map((conflict) => (
                      <div
                        key={conflict.dimension}
                        className="rounded-lg border border-[#f0e2c8] bg-white p-3"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-xs font-semibold text-[#5f4a1e]">{conflict.title}</p>
                          <span className="rounded-full bg-[#f6efdd] px-2 py-0.5 text-[10px] text-[#8a6228]">
                            {RESOLVED_BY_LABELS[conflict.resolvedBy] ?? conflict.resolvedBy}
                          </span>
                        </div>
                        <p className="mt-1.5 text-[11px] leading-relaxed text-[#7b6228]">
                          {conflict.message}
                        </p>
                        <p className="mt-1 text-[11px] leading-relaxed text-[#9a7c3a]">
                          建议：{conflict.suggestion}
                        </p>
                        <div className="mt-2 flex flex-wrap items-center gap-2">
                          <span className="text-[10px] text-[#9a7c3a]">处理方式</span>
                          <select
                            aria-label={`${conflict.title}处理方式`}
                            value={resolutions[conflict.dimension] ?? "auto"}
                            onChange={(event) =>
                              setConflictResolution(
                                conflict.dimension,
                                event.target.value as ConflictResolution,
                              )
                            }
                            className="min-h-9 rounded-lg border border-[#e6d6b4] bg-white px-2 text-[11px] text-[#5f4a1e] focus:border-[#c9b079] focus:outline-none"
                          >
                            {RESOLUTION_OPTIONS.map((option) => (
                              <option key={option.value} value={option.value}>
                                {option.label}
                              </option>
                            ))}
                          </select>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="grid gap-4 lg:grid-cols-2">
                <div className="rounded-xl border border-[#dfe5e1] bg-white p-4">
                  <h3 className="text-xs font-semibold text-[#33413a]">维度组合</h3>
                  <ul className="mt-3 space-y-2.5">
                    {preview.dimensions.map((dimension) => (
                      <li key={dimension.dimension} className="text-[11px] leading-relaxed">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium text-[#3b4841]">{dimension.title}</span>
                          <span className="text-[10px] text-[#8a9690]">
                            {dimension.source === "a"
                              ? "来自 A"
                              : dimension.source === "b"
                                ? "来自 B"
                                : "融合"}
                          </span>
                        </div>
                        <p className="mt-0.5 text-[#68746e]">{dimension.description}</p>
                      </li>
                    ))}
                  </ul>
                </div>
                <div className="space-y-4">
                  <div className="rounded-xl border border-[#dfe5e1] bg-white p-4">
                    <div className="flex items-center gap-2">
                      <ShieldCheckIcon className="size-4 text-[#277a68]" />
                      <h3 className="text-xs font-semibold text-[#33413a]">保护约束（并集）</h3>
                    </div>
                    <div className="mt-2.5 flex flex-wrap gap-1.5">
                      {preview.protections.map((protection) => (
                        <span
                          key={protection}
                          className="rounded-full bg-[#eef5f1] px-2.5 py-1 text-[10px] text-[#277a68]"
                        >
                          {protection}
                        </span>
                      ))}
                    </div>
                    <p className="mt-2 text-[10px] leading-relaxed text-[#9aa5a0]">
                      保护约束来自两种风格的并集，不会被权重平均或丢弃。
                    </p>
                  </div>
                  <TargetPreview profile={preview.profile} />
                </div>
              </div>

          {optionA !== null && optionB !== null && (traitsA !== null || traitsB !== null) && (
            <div className="grid gap-4 lg:grid-cols-2">
              <OriginalStyleCard label="风格 A" name={optionA.name} traits={traitsA} />
              <OriginalStyleCard label="风格 B" name={optionB.name} traits={traitsB} />
            </div>
          )}

              {preview.limitations.length > 0 && (
                <div className="rounded-xl border border-[#e4e8e5] bg-[#f7f9f7] p-4">
                  <h3 className="text-xs font-semibold text-[#55625b]">限制</h3>
                  <ul className="mt-2 list-disc space-y-1 pl-4 text-[11px] leading-relaxed text-[#7a8680]">
                    {preview.limitations.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="rounded-2xl border border-[#dfe5e1] bg-white p-5 sm:p-6">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-semibold text-[#202522]">保存为个人风格</h3>
                    <p className="mt-1 text-[11px] text-[#8a9690]">
                      会记录来源风格 ID 与版本、权重、组合规则与冲突处理，形成独立可复用的风格档案。
                    </p>
                  </div>
                  <SparkleIcon className="size-5 text-[#277a68]" />
                </div>
                <label className="mt-4 block">
                  <span className="text-xs font-medium text-[#4a574f]">混合风格名称</span>
                  <input
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    maxLength={64}
                    placeholder="例如：克制的城市 × 黑白街头"
                    className="mt-1.5 min-h-11 w-full rounded-xl border border-[#dfe5e1] px-3.5 text-sm text-[#2a3530] placeholder:text-[#a4aea9] focus:border-[#9dbdaf] focus:outline-none"
                  />
                </label>
                {saveError !== null && (
                  <p role="alert" className="mt-3 text-[11px] text-[#8a3a2e]">
                    {saveError}
                  </p>
                )}
                <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-[#eef1ef] pt-4">
                  <p className="text-[11px] text-[#8a9690]">
                    保存后为草稿状态，可在风格详情中发布并应用到新照片。
                  </p>
                  <button
                    type="button"
                    disabled={!canSave}
                    onClick={() => void handleSave()}
                    className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-[#277a68] px-5 text-sm font-medium text-white hover:bg-[#206557] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {saving ? "正在保存…" : "保存混合风格"}
                    <ArrowRightIcon className="size-4" />
                  </button>
                </div>
              </div>
            </section>
          )}
        </>
      )}
    </main>
  );
}

function StylePicker({
  label,
  value,
  options,
  excludedId,
  onChange,
}: {
  label: string;
  value: string;
  options: StyleOption[] | null;
  excludedId: string;
  onChange: (id: string) => void;
}) {
  const selected = options?.find((option) => option.id === value) ?? null;
  const masters = options?.filter((option) => option.group === "master") ?? [];
  const personals = options?.filter((option) => option.group === "personal") ?? [];
  return (
    <div className="rounded-2xl border border-[#dfe5e1] bg-white p-5">
      <label className="block">
        <span className="text-xs font-semibold text-[#4a574f]">{label}</span>
        <select
          aria-label={label}
          value={value}
          disabled={options === null}
          onChange={(event) => onChange(event.target.value)}
          className="mt-1.5 min-h-11 w-full rounded-xl border border-[#dfe5e1] bg-white px-3 text-sm text-[#2a3530] focus:border-[#9dbdaf] focus:outline-none disabled:opacity-50"
        >
          <option value="">选择风格…</option>
          {masters.length > 0 && (
            <optgroup label="大师 / 流派风格">
              {masters.map((option) => (
                <option
                  key={option.id}
                  value={option.id}
                  disabled={option.id === excludedId}
                >
                  {option.name}
                </option>
              ))}
            </optgroup>
          )}
          {personals.length > 0 && (
            <optgroup label="我的个人风格">
              {personals.map((option) => (
                <option
                  key={option.id}
                  value={option.id}
                  disabled={option.id === excludedId}
                >
                  {option.name}
                </option>
              ))}
            </optgroup>
          )}
        </select>
      </label>
      {selected !== null && (
        <div className="mt-3 rounded-xl bg-[#f7faf8] px-3.5 py-3">
          <p className="text-[10px] font-medium uppercase tracking-[0.18em] text-[#8a9a93]">
            {selected.sourceLabel} · v{selected.version}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-[#5f6d66]">{selected.description}</p>
        </div>
      )}
    </div>
  );
}

function TargetPreview({ profile }: { profile: PersonalStyleProfile }) {
  const targets = Object.entries(profile.personal.targets ?? {});
  return (
    <div className="rounded-xl border border-[#dfe5e1] bg-white p-4">
      <h3 className="text-xs font-semibold text-[#33413a]">目标参数预览</h3>
      {targets.length === 0 ? (
        <p className="mt-2 text-[11px] text-[#9aa5a0]">本次混合不产生数值偏移，以语义特征为主。</p>
      ) : (
        <dl className="mt-2.5 grid grid-cols-2 gap-x-4 gap-y-1.5">
          {targets.map(([key, value]) => (
            <div key={key} className="flex items-center justify-between gap-2 text-[11px]">
              <dt className="text-[#68746e]">{targetLabel(key)}</dt>
              <dd className="font-medium text-[#3b4841]">{formatTargetValue(value)}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

function OriginalStyleCard({
  label,
  name,
  traits,
}: {
  label: string;
  name: string;
  traits: StyleTraits | null;
}) {
  return (
    <div className="rounded-xl border border-[#dfe5e1] bg-white p-4">
      <p className="text-[10px] font-medium uppercase tracking-[0.18em] text-[#8a9a93]">
        {label} · 原始风格
      </p>
      <h3 className="mt-1 text-sm font-semibold text-[#202522]">{name}</h3>
      {traits === null ? (
        <p className="mt-2 text-[11px] text-[#9aa5a0]">正在加载原始风格特征…</p>
      ) : (
        <dl className="mt-2.5 space-y-1.5 text-[11px] leading-relaxed">
          <div>
            <dt className="inline font-medium text-[#4a574f]">色彩：</dt>
            <dd className="inline text-[#68746e]">{traits.color.tendency}</dd>
          </div>
          <div>
            <dt className="inline font-medium text-[#4a574f]">影调：</dt>
            <dd className="inline text-[#68746e]">{traits.light.contrast}</dd>
          </div>
          <div>
            <dt className="inline font-medium text-[#4a574f]">光线：</dt>
            <dd className="inline text-[#68746e]">{traits.light.expression}</dd>
          </div>
          <div>
            <dt className="inline font-medium text-[#4a574f]">质感：</dt>
            <dd className="inline text-[#68746e]">{traits.texture.grain}</dd>
          </div>
        </dl>
      )}
    </div>
  );
}