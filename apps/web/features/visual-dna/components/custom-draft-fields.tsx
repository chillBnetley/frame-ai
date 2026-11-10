"use client";

import { SCENE_LABELS } from "@/features/master-vision/presentation";
import type {
  PersonalAvoidEffect,
  StyleAuthoringDraft,
} from "@/types/personal-style";
import type { SceneLabel } from "@/types/style-library";

import {
  AVOID_OPTIONS,
  TARGET_FIELDS,
  TRAIT_FIELDS,
  formatTargetValue,
} from "../presentation";

const ALL_SCENES = Object.keys(SCENE_LABELS) as SceneLabel[];

export function CustomDraftFields({
  draft,
  onChange,
}: {
  draft: StyleAuthoringDraft;
  onChange: (next: StyleAuthoringDraft) => void;
}) {
  function updateTrait(
    section: "color" | "light" | "texture",
    field: string,
    value: string,
  ) {
    if (section === "color") {
      onChange({ ...draft, color: { ...draft.color, [field]: value } });
    } else if (section === "light") {
      onChange({ ...draft, light: { ...draft.light, [field]: value } });
    } else {
      onChange({ ...draft, texture: { ...draft.texture, [field]: value } });
    }
  }

  function toggleScene(scene: SceneLabel) {
    const active = draft.suitableScenes.includes(scene);
    if (active) {
      if (draft.suitableScenes.length <= 1) return;
      onChange({
        ...draft,
        suitableScenes: draft.suitableScenes.filter((item) => item !== scene),
      });
    } else {
      onChange({ ...draft, suitableScenes: [...draft.suitableScenes, scene] });
    }
  }

  function toggleAvoid(effect: PersonalAvoidEffect) {
    const active = draft.avoid.includes(effect);
    onChange({
      ...draft,
      avoid: active ? draft.avoid.filter((item) => item !== effect) : [...draft.avoid, effect],
    });
  }

  return (
    <div className="space-y-5">
      <section className="rounded-2xl border border-[#dfe5e1] bg-white p-5">
        <h2 className="text-sm font-semibold text-[#202522]">基础信息</h2>
        <div className="mt-4 grid gap-4">
          <label className="block">
            <span className="text-xs font-medium text-[#4a574f]">确认后的名称</span>
            <input
              value={draft.name}
              maxLength={64}
              onChange={(event) => onChange({ ...draft, name: event.target.value })}
              className="mt-1.5 min-h-11 w-full rounded-xl border border-[#dfe5e1] px-3.5 text-sm text-[#2a3530] focus:border-[#9dbdaf] focus:outline-none"
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-[#4a574f]">确认后的描述</span>
            <textarea
              value={draft.description}
              maxLength={500}
              rows={4}
              onChange={(event) =>
                onChange({ ...draft, description: event.target.value })
              }
              className="mt-1.5 w-full rounded-xl border border-[#dfe5e1] px-3.5 py-3 text-sm leading-relaxed text-[#2a3530] focus:border-[#9dbdaf] focus:outline-none"
            />
          </label>
        </div>
      </section>

      <section className="rounded-2xl border border-[#dfe5e1] bg-white p-5">
        <h2 className="text-sm font-semibold text-[#202522]">文字风格特征</h2>
        <div className="mt-4 grid gap-x-6 gap-y-3 sm:grid-cols-2">
          {TRAIT_FIELDS.map((field) => {
            const section = draft[field.section] as Record<string, string>;
            return (
              <label key={field.key} className="block">
                <span className="text-xs font-medium text-[#4a574f]">{field.label}</span>
                <input
                  value={section[field.field] ?? ""}
                  placeholder={field.placeholder}
                  maxLength={500}
                  onChange={(event) =>
                    updateTrait(field.section, field.field, event.target.value)
                  }
                  className="mt-1.5 min-h-10 w-full rounded-xl border border-[#dfe5e1] px-3 text-xs text-[#2a3530] placeholder:text-[#a4aea9] focus:border-[#9dbdaf] focus:outline-none"
                />
              </label>
            );
          })}
        </div>
      </section>

      <section className="rounded-2xl border border-[#dfe5e1] bg-white p-5">
        <h2 className="text-sm font-semibold text-[#202522]">数值偏好</h2>
        <div className="mt-4 grid gap-x-6 gap-y-4 sm:grid-cols-2">
          {TARGET_FIELDS.map((field) => {
            const value = (draft.targets ?? {})[field.key] ?? 0;
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
                  aria-label={`${field.label}偏好`}
                  min={field.min}
                  max={field.max}
                  step={field.step}
                  value={value}
                  onChange={(event) =>
                    onChange({
                      ...draft,
                      targets: {
                        ...(draft.targets ?? {}),
                        [field.key]: Number(event.target.value),
                      },
                    })
                  }
                  className="mt-2 w-full accent-[#277a68]"
                />
              </label>
            );
          })}
        </div>
      </section>

      <section className="rounded-2xl border border-[#dfe5e1] bg-white p-5">
        <h2 className="text-sm font-semibold text-[#202522]">适用场景</h2>
        <div className="mt-3 flex flex-wrap gap-2">
          {ALL_SCENES.map((scene) => {
            const active = draft.suitableScenes.includes(scene);
            return (
              <button
                key={scene}
                type="button"
                aria-pressed={active}
                onClick={() => toggleScene(scene)}
                className="inline-flex min-h-9 items-center rounded-full border border-[#dfe5e1] bg-white px-3 text-[11px] text-[#5f6d66] hover:border-[#b9cdc2] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent aria-pressed:border-[#277a68] aria-pressed:bg-[#f0f7f4] aria-pressed:text-[#277a68]"
              >
                {SCENE_LABELS[scene]}
              </button>
            );
          })}
        </div>
        <label className="mt-4 block">
          <span className="text-xs font-medium text-[#4a574f]">不适用场景说明</span>
          <input
            value={draft.unsuitableNotes}
            maxLength={500}
            onChange={(event) =>
              onChange({ ...draft, unsuitableNotes: event.target.value })
            }
            className="mt-1.5 min-h-10 w-full rounded-xl border border-[#dfe5e1] px-3 text-xs text-[#2a3530] focus:border-[#9dbdaf] focus:outline-none"
          />
        </label>
      </section>

      <section className="rounded-2xl border border-[#dfe5e1] bg-white p-5">
        <h2 className="text-sm font-semibold text-[#202522]">不希望出现的效果</h2>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {AVOID_OPTIONS.map(([effect, label]) => (
            <label
              key={effect}
              className="flex items-center gap-2 rounded-lg border border-[#eef1ef] bg-[#f9fbf9] px-3 py-2 text-[11px] text-[#4a574f]"
            >
              <input
                type="checkbox"
                checked={draft.avoid.includes(effect)}
                onChange={() => toggleAvoid(effect)}
                className="size-4 accent-[#277a68]"
              />
              {label}
            </label>
          ))}
        </div>
      </section>
    </div>
  );
}
