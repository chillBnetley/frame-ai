"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { SCENE_LABELS } from "@/features/master-vision/presentation";
import { MasterVisionStatus } from "@/features/master-vision/components/status";
import { ApiClientError } from "@/lib/api/client";
import {
  fetchPersonalStyle,
  updatePersonalStyle,
} from "@/lib/api/personal-style";
import type {
  PersonalAvoidEffect,
  PersonalStyleDetailResponse,
  PersonalStyleTraitUpdate,
  PersonalStyleUpdateRequest,
} from "@/types/personal-style";
import type { SceneLabel } from "@/types/style-library";

import { VisualDnaNav } from "./visual-dna-nav";
import {
  AVOID_OPTIONS,
  TARGET_FIELDS,
  TRAIT_FIELDS,
  formatPercent,
  formatTargetValue,
  traitValuesFrom,
  type TraitKey,
  type TraitValues,
} from "../presentation";

const ALL_SCENES = Object.keys(SCENE_LABELS) as SceneLabel[];

function targetsFrom(detail: PersonalStyleDetailResponse): Record<string, number> {
  const targets = detail.style.personal.targets ?? {};
  const initial: Record<string, number> = { ...targets };
  for (const field of TARGET_FIELDS) {
    initial[field.key] = targets[field.key] ?? 0;
  }
  return initial;
}

function sameTargets(left: Record<string, number>, right: Record<string, number>): boolean {
  return TARGET_FIELDS.every((field) => (left[field.key] ?? 0) === (right[field.key] ?? 0));
}

function sameList(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((item, index) => item === right[index]);
}

function sameTraits(left: TraitValues, right: TraitValues): boolean {
  return TRAIT_FIELDS.every((field) => left[field.key].trim() === right[field.key].trim());
}

export function VisualDnaEditor({ styleId }: { styleId: string }) {
  const router = useRouter();
  const [detail, setDetail] = useState<PersonalStyleDetailResponse | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [scenes, setScenes] = useState<SceneLabel[]>([]);
  const [targets, setTargets] = useState<Record<string, number>>({});
  const [avoid, setAvoid] = useState<PersonalAvoidEffect[]>([]);
  const [traits, setTraits] = useState<TraitValues | null>(null);
  const [note, setNote] = useState("");
  const [initial, setInitial] = useState<{
    name: string;
    description: string;
    scenes: SceneLabel[];
    targets: Record<string, number>;
    avoid: PersonalAvoidEffect[];
    traits: TraitValues;
  } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    fetchPersonalStyle(styleId, { signal: controller.signal })
      .then((response) => {
        if (controller.signal.aborted) return;
        setDetail(response);
        setName(response.style.name);
        setDescription(response.style.description);
        setScenes([...response.style.sceneFit.suitable]);
        setTargets(targetsFrom(response));
        setAvoid([...response.style.personal.avoid]);
        const loadedTraits = traitValuesFrom(response.style);
        setTraits(loadedTraits);
        setInitial({
          name: response.style.name,
          description: response.style.description,
          scenes: [...response.style.sceneFit.suitable],
          targets: targetsFrom(response),
          avoid: [...response.style.personal.avoid],
          traits: loadedTraits,
        });
        setLoadError(null);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setLoadError(
            reason instanceof ApiClientError
              ? reason.message
              : "无法加载个人风格，请确认 API 服务已经启动。",
          );
        }
      });
    return () => controller.abort();
  }, [attempt, styleId]);

  if (loadError !== null) {
    return (
      <main className="mx-auto w-full max-w-[1080px] px-4 py-6 sm:px-6 lg:px-8">
        <VisualDnaNav />
        <div className="mt-5">
          <MasterVisionStatus
            tone="error"
            title="编辑器加载失败"
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
            {loadError}
          </MasterVisionStatus>
        </div>
      </main>
    );
  }

  if (detail === null || initial === null || traits === null) {
    return (
      <main className="mx-auto w-full max-w-[1080px] px-4 py-6 sm:px-6 lg:px-8">
        <VisualDnaNav />
        <div className="mt-6 h-48 animate-pulse rounded-2xl border border-[#e4e8e5] bg-[#f4f7f5]" />
      </main>
    );
  }

  const sceneDirty = !sameList(scenes, initial.scenes);
  const targetDirty = !sameTargets(targets, initial.targets);
  const avoidDirty = !sameList(avoid, initial.avoid);
  const traitsDirty = !sameTraits(traits, initial.traits);
  const traitsValid = TRAIT_FIELDS.every((field) => traits[field.key].trim().length > 0);
  const dirty =
    name.trim() !== initial.name ||
    description.trim() !== initial.description ||
    sceneDirty ||
    targetDirty ||
    avoidDirty ||
    traitsDirty ||
    note.trim().length > 0;
  const valid =
    name.trim().length > 0 &&
    name.trim().length <= 64 &&
    description.trim().length > 0 &&
    description.trim().length <= 500 &&
    scenes.length > 0 &&
    traitsValid &&
    dirty &&
    !busy;
  const currentScenes = detail.style.sceneFit.suitable;

  function toggleScene(scene: SceneLabel) {
    setScenes((current) => {
      if (current.includes(scene)) {
        return current.length > 1 ? current.filter((item) => item !== scene) : current;
      }
      return [...current, scene];
    });
  }

  function toggleAvoid(effect: PersonalAvoidEffect) {
    setAvoid((current) =>
      current.includes(effect)
        ? current.filter((item) => item !== effect)
        : [...current, effect],
    );
  }

  async function handleSave() {
    if (!valid || initial === null || traits === null) return;
    const payload: PersonalStyleUpdateRequest = {};
    if (name.trim() !== initial.name) payload.name = name.trim();
    if (description.trim() !== initial.description) payload.description = description.trim();
    if (sceneDirty) payload.suitableScenes = scenes;
    if (targetDirty) {
      const next: Record<string, number> = { ...initial.targets };
      for (const field of TARGET_FIELDS) {
        const value = targets[field.key] ?? 0;
        if (value !== 0 || initial.targets[field.key] !== undefined) {
          next[field.key] = value;
        }
      }
      payload.targets = next;
    }
    if (avoidDirty) payload.avoid = avoid;
    if (traitsDirty) {
      const next: Partial<Record<TraitKey, string>> = {};
      for (const field of TRAIT_FIELDS) {
        const value = traits[field.key].trim();
        if (value !== initial.traits[field.key].trim()) {
          next[field.key] = value;
        }
      }
      payload.traits = next as PersonalStyleTraitUpdate;
    }
    if (note.trim().length > 0) payload.note = note.trim();
    setBusy(true);
    setSaveError(null);
    try {
      await updatePersonalStyle(styleId, payload);
      router.push(`/visual-dna/${encodeURIComponent(styleId)}`);
    } catch (reason: unknown) {
      setSaveError(
        reason instanceof ApiClientError ? reason.message : "保存失败，请稍后重试。",
      );
      setBusy(false);
    }
  }

  function resetForm() {
    if (initial === null) return;
    setName(initial.name);
    setDescription(initial.description);
    setScenes([...initial.scenes]);
    setTargets({ ...initial.targets });
    setAvoid([...initial.avoid]);
    setTraits({ ...initial.traits });
    setNote("");
    setSaveError(null);
  }

  return (
    <main className="mx-auto w-full max-w-[1080px] px-4 py-6 sm:px-6 lg:px-8">
      <VisualDnaNav />
      <div className="mt-6 flex flex-wrap items-end justify-between gap-4 border-b border-[#e4e8e5] pb-5">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.28em] text-[#8a9a93]">
            EDIT VISUAL DNA
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-[-0.045em] text-[#1d2521]">
            编辑「{initial.name}」
          </h1>
          <p className="mt-2 text-sm text-[#68746e]">
            当前 v{detail.style.version} · 置信度 {formatPercent(detail.style.personal.confidence)}
          </p>
        </div>
        <Link
          href={`/visual-dna/${encodeURIComponent(styleId)}`}
          className="text-xs font-medium text-[#277a68] hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          ← 返回工作台
        </Link>
      </div>

      <div className="mt-4 rounded-xl border border-[#eadfc4] bg-[#fbf7ec] px-4 py-3 text-[11px] leading-relaxed text-[#7b6228]">
        你在这里手动修改的内容会被标记为用户确认。之后重新分析或融合参考照片时，
        这些字段不会被静默覆盖；每次保存都会形成新的风格版本。
      </div>

      <div className="mt-6 space-y-6">
        <section className="rounded-2xl border border-[#dfe5e1] bg-white p-5 sm:p-6">
          <h2 className="text-sm font-semibold text-[#202522]">基础信息</h2>
          <div className="mt-4 grid gap-4">
            <label className="block">
              <span className="text-xs font-medium text-[#4a574f]">风格名称</span>
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                maxLength={64}
                className="mt-1.5 min-h-11 w-full rounded-xl border border-[#dfe5e1] bg-white px-3.5 text-sm text-[#2a3530] focus:border-[#9dbdaf] focus:outline-none"
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-[#4a574f]">风格描述</span>
              <textarea
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                maxLength={500}
                rows={5}
                className="mt-1.5 w-full rounded-xl border border-[#dfe5e1] bg-white px-3.5 py-3 text-sm leading-relaxed text-[#2a3530] focus:border-[#9dbdaf] focus:outline-none"
              />
              <span className="mt-1 block text-right text-[10px] text-[#9aa5a0]">
                {description.length} / 500
              </span>
            </label>
          </div>
        </section>

        <section className="rounded-2xl border border-[#dfe5e1] bg-white p-5 sm:p-6">
          <h2 className="text-sm font-semibold text-[#202522]">色彩、影调与质感偏好</h2>
          <p className="mt-1 text-[11px] text-[#8a9690]">
            数值是有界建议，最终仍会经过包络、转换模式与配方校验。
          </p>
          <div className="mt-4 grid gap-x-6 gap-y-4 sm:grid-cols-2">
            {TARGET_FIELDS.map((field) => {
              const value = targets[field.key] ?? 0;
              return (
                <label key={field.key} className="block">
                  <span className="flex items-center justify-between text-xs text-[#4a574f]">
                    <span>{field.label}</span>
                    <span className="font-semibold text-[#2c3a34]">
                      {formatTargetValue(value)}
                    </span>
                  </span>
                  <input
                    type="range"
                    aria-label={field.label}
                    min={field.min}
                    max={field.max}
                    step={field.step}
                    value={value}
                    onChange={(event) =>
                      setTargets((current) => ({
                        ...current,
                        [field.key]: Number(event.target.value),
                      }))
                    }
                    className="mt-2 w-full accent-[#277a68]"
                  />
                  <span className="mt-0.5 flex justify-between text-[9px] text-[#9aa5a0]">
                    <span>{field.min}</span>
                    <span>{field.max}</span>
                  </span>
                </label>
              );
            })}
          </div>
        </section>

        <section className="rounded-2xl border border-[#dfe5e1] bg-white p-5 sm:p-6">
          <h2 className="text-sm font-semibold text-[#202522]">文字风格特征</h2>
          <p className="mt-1 text-[11px] text-[#8a9690]">
            这些描述会进入 AI 规划上下文；修改后同样按用户确认优先保留。
          </p>
          <div className="mt-4 grid gap-x-6 gap-y-3 sm:grid-cols-2">
            {TRAIT_FIELDS.map((field) => (
              <label key={field.key} className="block">
                <span className="text-xs font-medium text-[#4a574f]">{field.label}</span>
                <input
                  value={traits[field.key]}
                  placeholder={field.placeholder}
                  maxLength={500}
                  onChange={(event) =>
                    setTraits((current) =>
                      current === null
                        ? current
                        : { ...current, [field.key]: event.target.value },
                    )
                  }
                  className="mt-1.5 min-h-10 w-full rounded-xl border border-[#dfe5e1] bg-white px-3 text-xs text-[#2a3530] placeholder:text-[#a4aea9] focus:border-[#9dbdaf] focus:outline-none"
                />
              </label>
            ))}
          </div>
        </section>

        <section className="rounded-2xl border border-[#dfe5e1] bg-white p-5 sm:p-6">
          <h2 className="text-sm font-semibold text-[#202522]">适用场景</h2>
          <div className="mt-3 flex flex-wrap gap-2">
            {ALL_SCENES.map((scene) => {
              const active = scenes.includes(scene);
              const current = currentScenes.includes(scene);
              return (
                <button
                  key={scene}
                  type="button"
                  aria-pressed={active}
                  onClick={() => toggleScene(scene)}
                  className="inline-flex min-h-9 items-center gap-1.5 rounded-full border border-[#dfe5e1] bg-white px-3 text-[11px] text-[#5f6d66] hover:border-[#b9cdc2] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent aria-pressed:border-[#277a68] aria-pressed:bg-[#f0f7f4] aria-pressed:text-[#277a68]"
                >
                  {SCENE_LABELS[scene]}
                  {current && !active && <span className="text-[9px] text-[#9aa5a0]">·原</span>}
                </button>
              );
            })}
          </div>
          <p className="mt-2 text-[10px] text-[#8a9690]">至少保留一个适用场景。</p>
        </section>

        <section className="rounded-2xl border border-[#dfe5e1] bg-white p-5 sm:p-6">
          <h2 className="text-sm font-semibold text-[#202522]">不希望出现的效果</h2>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {AVOID_OPTIONS.map(([effect, label]) => (
              <label
                key={effect}
                className="flex items-center gap-2 rounded-lg border border-[#eef1ef] bg-[#f9fbf9] px-3 py-2 text-[11px] text-[#4a574f]"
              >
                <input
                  type="checkbox"
                  checked={avoid.includes(effect)}
                  onChange={() => toggleAvoid(effect)}
                  className="size-4 accent-[#277a68]"
                />
                {label}
              </label>
            ))}
          </div>
        </section>

        <section className="rounded-2xl border border-[#dfe5e1] bg-white p-5 sm:p-6">
          <h2 className="text-sm font-semibold text-[#202522]">版本说明</h2>
          <input
            value={note}
            onChange={(event) => setNote(event.target.value)}
            maxLength={500}
            placeholder="可选：记录这次修改的原因"
            className="mt-3 min-h-11 w-full rounded-xl border border-[#dfe5e1] bg-white px-3.5 text-sm text-[#2a3530] placeholder:text-[#a4aea9] focus:border-[#9dbdaf] focus:outline-none"
          />
        </section>

        {saveError !== null && (
          <MasterVisionStatus tone="error" title="保存未完成">
            {saveError}
          </MasterVisionStatus>
        )}

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#e4e8e5] pt-4">
          <button
            type="button"
            onClick={resetForm}
            disabled={!dirty || busy}
            className="inline-flex min-h-10 items-center rounded-xl border border-[#d7dfda] bg-white px-4 text-xs font-medium text-[#415049] hover:bg-[#f7faf8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50"
          >
            撤销未保存修改
          </button>
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={!valid}
            className="inline-flex min-h-11 items-center rounded-xl bg-[#277a68] px-5 text-sm font-medium text-white hover:bg-[#206557] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? "保存中…" : "保存为新版本"}
          </button>
        </div>
      </div>
    </main>
  );
}
