"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { ArrowRightIcon, SparkleIcon } from "@/components/icons";
import { SCENE_LABELS } from "@/features/master-vision/presentation";
import { MasterVisionStatus } from "@/features/master-vision/components/status";
import { ApiClientError } from "@/lib/api/client";
import {
  parseCustomStyle,
  saveCustomStyle,
} from "@/lib/api/personal-style";
import type {
  CustomStyleParseResponse,
  StyleAuthoringDraft,
} from "@/types/personal-style";
import type { SceneLabel } from "@/types/style-library";

import { CustomDraftFields } from "./custom-draft-fields";
import { VisualDnaNav } from "./visual-dna-nav";
import { formatPercent } from "../presentation";

const ALL_SCENES = Object.keys(SCENE_LABELS) as SceneLabel[];

export function VisualDnaCustom() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [avoid, setAvoid] = useState("");
  const [scenes, setScenes] = useState<SceneLabel[]>([]);
  const [result, setResult] = useState<CustomStyleParseResponse | null>(null);
  const [draft, setDraft] = useState<StyleAuthoringDraft | null>(null);
  const [parsing, setParsing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canParse =
    name.trim().length > 0 && description.trim().length > 0 && !parsing && !saving;
  const canSave =
    draft !== null &&
    draft.name.trim().length > 0 &&
    draft.description.trim().length > 0 &&
    draft.suitableScenes.length > 0 &&
    !saving;

  async function handleParse(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canParse) return;
    setParsing(true);
    setError(null);
    try {
      const response = await parseCustomStyle({
        name: name.trim(),
        description: description.trim(),
        avoid: avoid.trim() || null,
        suitableScenes: scenes,
      });
      setResult(response);
      setDraft(response.draft);
    } catch (reason: unknown) {
      setError(
        reason instanceof ApiClientError
          ? reason.message
          : "无法解析风格描述，请确认 API 与模型 Provider 已就绪。",
      );
    } finally {
      setParsing(false);
    }
  }

  async function handleSave() {
    if (draft === null || !canSave) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await saveCustomStyle(draft, {
        note: "由自然语言创建并确认。",
      });
      router.push(`/visual-dna/${encodeURIComponent(saved.style.id)}`);
    } catch (reason: unknown) {
      setError(
        reason instanceof ApiClientError ? reason.message : "保存个人风格失败，请稍后重试。",
      );
      setSaving(false);
    }
  }

  function toggleScene(scene: SceneLabel) {
    setScenes((current) =>
      current.includes(scene)
        ? current.filter((item) => item !== scene)
        : [...current, scene],
    );
  }

  return (
    <main className="mx-auto w-full max-w-[1280px] px-4 py-6 sm:px-6 lg:px-8">
      <VisualDnaNav />
      <div className="mt-6 flex flex-wrap items-end justify-between gap-4 border-b border-[#e4e8e5] pb-5">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.28em] text-[#8a9a93]">
            CUSTOM STYLE CREATOR
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-[-0.045em] text-[#1d2521] sm:text-4xl">
            用自然语言创建个人风格
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-[#68746e]">
            描述你想要的色彩、影调、光线与质感。AI 只生成受校验的结构化风格档案，
            不会把自然语言直接变成未校验的调色参数。
          </p>
        </div>
        <Link
          href="/visual-dna"
          className="text-xs font-medium text-[#277a68] hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          ← 返回我的风格
        </Link>
      </div>

      <form onSubmit={(event) => void handleParse(event)} className="mt-6 space-y-5">
        <section className="rounded-2xl border border-[#dfe5e1] bg-white p-5 sm:p-6">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-[#202522]">描述你的风格</h2>
              <p className="mt-1 text-[11px] text-[#8a9690]">
                可以直接写颜色、影调、光线、质感、适用场景和不希望出现的效果。
              </p>
            </div>
            <SparkleIcon className="size-5 text-[#277a68]" />
          </div>
          <div className="mt-4 grid gap-4">
            <label className="block">
              <span className="text-xs font-medium text-[#4a574f]">风格名称</span>
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                maxLength={64}
                placeholder="例如：克制的城市叙事"
                className="mt-1.5 min-h-11 w-full rounded-xl border border-[#dfe5e1] px-3.5 text-sm text-[#2a3530] placeholder:text-[#a4aea9] focus:border-[#9dbdaf] focus:outline-none"
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-[#4a574f]">风格描述</span>
              <textarea
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                maxLength={500}
                rows={5}
                placeholder="例如：我希望照片低饱和、偏冷，但保留真实的街头质感；暗部不要压黑，人物肤色保持自然。"
                className="mt-1.5 w-full rounded-xl border border-[#dfe5e1] px-3.5 py-3 text-sm leading-relaxed text-[#2a3530] placeholder:text-[#a4aea9] focus:border-[#9dbdaf] focus:outline-none"
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-[#4a574f]">
                不希望出现的效果
                <span className="ml-1 font-normal text-[#9aa5a0]">可选</span>
              </span>
              <input
                value={avoid}
                onChange={(event) => setAvoid(event.target.value)}
                maxLength={500}
                placeholder="例如：不要过饱和，不要压黑暗部，不要明显滤镜感"
                className="mt-1.5 min-h-11 w-full rounded-xl border border-[#dfe5e1] px-3.5 text-sm text-[#2a3530] placeholder:text-[#a4aea9] focus:border-[#9dbdaf] focus:outline-none"
              />
            </label>
            <fieldset>
              <legend className="text-xs font-medium text-[#4a574f]">
                场景提示
                <span className="ml-1 font-normal text-[#9aa5a0]">可选</span>
              </legend>
              <div className="mt-2 flex flex-wrap gap-2">
                {ALL_SCENES.map((scene) => (
                  <button
                    key={scene}
                    type="button"
                    aria-pressed={scenes.includes(scene)}
                    onClick={() => toggleScene(scene)}
                    className="inline-flex min-h-9 items-center rounded-full border border-[#dfe5e1] bg-white px-3 text-[11px] text-[#5f6d66] hover:border-[#b9cdc2] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent aria-pressed:border-[#277a68] aria-pressed:bg-[#f0f7f4] aria-pressed:text-[#277a68]"
                  >
                    {SCENE_LABELS[scene]}
                  </button>
                ))}
              </div>
            </fieldset>
          </div>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-[#eef1ef] pt-4">
            <p className="text-[11px] text-[#8a9690]">
              解析会调用当前配置的文本模型；结果只作为结构化风格草稿。
            </p>
            <button
              type="submit"
              disabled={!canParse}
              className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-[#277a68] px-5 text-sm font-medium text-white hover:bg-[#206557] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              {parsing ? "正在理解…" : "解析风格"}
              <ArrowRightIcon className="size-4" />
            </button>
          </div>
        </section>
      </form>

      {error !== null && (
        <div className="mt-5">
          <MasterVisionStatus tone="error" title="操作未完成">
            {error}
          </MasterVisionStatus>
        </div>
      )}

      {result !== null && draft !== null && (
        <section aria-labelledby="draft-heading" className="mt-8 space-y-5">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-[#8a9a93]">
                AI UNDERSTANDING
              </p>
              <h2 id="draft-heading" className="mt-1 text-2xl font-semibold tracking-[-0.04em] text-[#1d2521]">
                AI 理解的风格
              </h2>
              <p className="mt-1 text-[11px] text-[#8a9690]">
                {result.provider.name} / {result.provider.model} · 置信度{" "}
                {formatPercent(draft.confidence)}
                {result.provider.isMock ? " · 模拟解析" : ""}
              </p>
            </div>
            <button
              type="button"
              onClick={() => {
                setResult(null);
                setDraft(null);
                setError(null);
              }}
              className="inline-flex min-h-10 items-center rounded-xl border border-[#d7dfda] bg-white px-4 text-xs font-medium text-[#415049] hover:bg-[#f7faf8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              重新描述
            </button>
          </div>

          <div className="whitespace-pre-line rounded-xl border border-[#dfe5e1] bg-[#f9fbf9] px-4 py-3 text-xs leading-relaxed text-[#3b4841]">
            {draft.summary}
          </div>

          {draft.rationale.length > 0 && (
            <div className="rounded-xl border border-[#dfe5e1] bg-white p-4">
              <h3 className="text-xs font-semibold text-[#33413a]">解析依据</h3>
              <ul className="mt-2 list-disc space-y-1 pl-4 text-[11px] leading-relaxed text-[#7a8680]">
                {draft.rationale.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          )}

          {draft.warnings.length > 0 && (
            <div className="rounded-xl border border-[#efd9b5] bg-[#fdfaf3] p-4">
              <h3 className="text-xs font-semibold text-[#8a6228]">需要确认</h3>
              <ul className="mt-2 list-disc space-y-1 pl-4 text-[11px] leading-relaxed text-[#7b6228]">
                {draft.warnings.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          )}

          {draft.limitations.length > 0 && (
            <div className="rounded-xl border border-[#e4e8e5] bg-[#f7f9f7] p-4">
              <h3 className="text-xs font-semibold text-[#55625b]">限制</h3>
              <ul className="mt-2 list-disc space-y-1 pl-4 text-[11px] leading-relaxed text-[#7a8680]">
                {draft.limitations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          )}

          <CustomDraftFields draft={draft} onChange={setDraft} />

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#e4e8e5] pt-4">
            <p className="text-[11px] text-[#8a9690]">
              保存后会创建个人风格草稿；手动修改过的字段会按用户确认优先保留。
            </p>
            <button
              type="button"
              disabled={!canSave}
              onClick={() => void handleSave()}
              className="inline-flex min-h-11 items-center rounded-xl bg-[#277a68] px-5 text-sm font-medium text-white hover:bg-[#206557] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              {saving ? "正在保存…" : "保存个人风格"}
            </button>
          </div>
        </section>
      )}
    </main>
  );
}
