"use client";

import { useId, useState } from "react";

import { MaskCanvas } from "./mask-canvas";
import { SliderField } from "./slider-field";
import {
  ADJUSTMENT_RANGES,
  LOCAL_ADJUSTMENT_LIMIT,
  LOCAL_V1_ADJUSTMENT_KEYS,
  MASK_LIMIT,
  MASK_RANGES,
  addLocalAdjustment,
  addMask,
  createLocalAdjustmentId,
  createMask,
  createMaskId,
  normalizeRecipe,
  removeLocalAdjustment,
  resetLocalAdjustment,
  roundTo4,
  setLocalAdjustmentEnabled,
  setLocalAdjustmentMask,
  updateLocalAdjustment,
  updateMask,
  type LocalV1AdjustmentKey,
} from "@/lib/recipe";
import {
  maskOutlinePoints,
  outlineOverlapsDisplay,
  previewMaskGeometry,
  type NormalizedRect,
  type Size,
} from "@/lib/mask-geometry";
import type { EditorRecipe, MaskShape, UserMask } from "@/types/session";

interface LocalFieldDefinition {
  key: LocalV1AdjustmentKey;
  label: string;
  unit?: string;
}

const LOCAL_FIELDS: readonly LocalFieldDefinition[] = [
  { key: "exposureEv", label: "局部曝光", unit: "EV" },
  { key: "contrast", label: "局部对比度" },
  { key: "highlights", label: "局部高光" },
  { key: "shadows", label: "局部阴影" },
  { key: "whites", label: "局部白色色阶" },
  { key: "blacks", label: "局部黑色色阶" },
  { key: "temperature", label: "局部色温" },
  { key: "tint", label: "局部色调" },
  { key: "saturation", label: "局部饱和度" },
  { key: "vibrance", label: "局部自然饱和度" },
  { key: "clarity", label: "局部清晰度" },
];

type MaskMode = "full" | MaskShape;

const MASK_MODES: readonly { id: MaskMode; label: string }[] = [
  { id: "full", label: "全图" },
  { id: "rectangle", label: "矩形" },
  { id: "ellipse", label: "椭圆" },
];

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

interface MaskPercentFieldProps {
  label: string;
  value: number;
  min: number;
  max: number;
  disabled: boolean;
  onChange: (value: number) => void;
  onCommit: () => void;
}

function MaskPercentField({
  label,
  value,
  min,
  max,
  disabled,
  onChange,
  onCommit,
}: MaskPercentFieldProps) {
  const id = useId();
  const [text, setText] = useState<string | null>(null);

  return (
    <div className="grid gap-1">
      <label htmlFor={id} className="text-[10px] text-white/45">
        {label}
      </label>
      <input
        id={id}
        type="number"
        inputMode="decimal"
        min={min}
        max={max}
        step={0.01}
        value={text ?? (value * 100).toFixed(2)}
        disabled={disabled}
        onChange={(event) => {
          const raw = event.target.value;
          setText(raw);
          const parsed = Number.parseFloat(raw);
          if (Number.isFinite(parsed)) {
            onChange(roundTo4(clamp(parsed, min, max) / 100));
          }
        }}
        onBlur={() => {
          setText(null);
          onCommit();
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            setText(null);
            onCommit();
          }
        }}
        className="w-full rounded-md border border-white/12 bg-black/35 px-2 py-1.5 font-mono text-[11px] text-white/80 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40"
      />
    </div>
  );
}

function addButtonClass(disabled: boolean): string {
  return `min-h-9 rounded-lg border px-2 text-[11px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
    disabled
      ? "cursor-not-allowed border-white/8 text-white/25"
      : "border-white/12 bg-white/[0.03] text-white/70 hover:bg-white/[0.07] hover:text-white"
  }`;
}

export interface LocalAdjustmentsPanelProps {
  recipe: EditorRecipe;
  previewUrl: string | null;
  previewWidth: number;
  previewHeight: number;
  sourceSize: Size | null;
  renderWarnings?: readonly string[];
  disabled?: boolean;
  onChange: (recipe: EditorRecipe) => void;
  onCommit: () => void;
}

export function LocalAdjustmentsPanel({
  recipe,
  previewUrl,
  previewWidth,
  previewHeight,
  sourceSize,
  renderWarnings = [],
  disabled = false,
  onChange,
  onCommit,
}: LocalAdjustmentsPanelProps) {
  const headingId = useId();
  const hintId = useId();
  const splitHintId = useId();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const items = recipe.localAdjustments;
  const masksById = new Map(recipe.masks.map((mask) => [mask.id, mask]));
  const activeId = items.some((item) => item.id === selectedId)
    ? selectedId
    : (items[0]?.id ?? null);
  const rotationDeg = recipe.adjustments.rotationDeg;
  const crop = recipe.adjustments.crop ?? null;
  const canAdd = !disabled && items.length < LOCAL_ADJUSTMENT_LIMIT;
  const canCreateMask = canAdd && recipe.masks.length < MASK_LIMIT;
  const geometry = previewMaskGeometry(
    { width: previewWidth, height: previewHeight },
    rotationDeg,
    crop,
    sourceSize,
  );

  const apply = (next: EditorRecipe) => {
    onChange(next);
    onCommit();
  };

  const addRegion = (shape: MaskShape) => {
    if (!canCreateMask) {
      return;
    }
    const maskId = createMaskId(recipe.masks);
    const localId = createLocalAdjustmentId(items);
    let next = addMask(recipe, { ...createMask(maskId), shape });
    next = addLocalAdjustment(next, maskId);
    setSelectedId(localId);
    apply(next);
  };

  const addFull = () => {
    if (!canAdd) {
      return;
    }
    const localId = createLocalAdjustmentId(items);
    setSelectedId(localId);
    apply(addLocalAdjustment(recipe, "full"));
  };

  const switchMaskMode = (itemId: string, mask: UserMask | null, mode: MaskMode) => {
    if (mode === "full") {
      const next = setLocalAdjustmentMask(recipe, itemId, "full");
      const referenced = new Set(next.localAdjustments.map((item) => item.maskId));
      apply(
        normalizeRecipe({
          ...next,
          masks: next.masks.filter((candidate) => referenced.has(candidate.id)),
        }),
      );
      return;
    }
    if (mask) {
      apply(updateMask(recipe, mask.id, { shape: mode }));
      return;
    }
    if (!canCreateMask) {
      return;
    }
    const maskId = createMaskId(recipe.masks);
    let next = addMask(recipe, { ...createMask(maskId), shape: mode });
    next = setLocalAdjustmentMask(next, itemId, maskId);
    apply(next);
  };

  const updateRegion = (mask: UserMask, region: NormalizedRect) => {
    onChange(updateMask(recipe, mask.id, region));
  };

  return (
    <section
      aria-labelledby={headingId}
      aria-describedby={hintId}
      className="grid gap-3 rounded-xl border border-white/8 bg-white/[0.015] p-4"
    >
      <div className="flex items-center justify-between gap-2">
        <h4 id={headingId} className="text-xs font-medium text-white/80">
          局部调整
        </h4>
        <span className="font-mono text-[9px] uppercase tracking-[0.12em] text-white/30">
          {items.length} / {LOCAL_ADJUSTMENT_LIMIT}
        </span>
      </div>

      <div className="grid gap-2">
        <div className="grid grid-cols-3 gap-1">
          <button
            type="button"
            onClick={() => addRegion("rectangle")}
            disabled={!canCreateMask}
            className={addButtonClass(!canCreateMask)}
          >
            添加矩形区域
          </button>
          <button
            type="button"
            onClick={() => addRegion("ellipse")}
            disabled={!canCreateMask}
            className={addButtonClass(!canCreateMask)}
          >
            添加椭圆区域
          </button>
          <button
            type="button"
            onClick={addFull}
            disabled={!canAdd}
            className={addButtonClass(!canAdd)}
          >
            添加全图局部调整
          </button>
        </div>
        <div className="grid grid-cols-2 gap-1">
          <button
            type="button"
            disabled
            aria-describedby={splitHintId}
            className="min-h-9 cursor-not-allowed rounded-lg border border-white/8 px-2 text-[11px] text-white/25"
          >
            人物蒙版
          </button>
          <button
            type="button"
            disabled
            aria-describedby={splitHintId}
            className="min-h-9 cursor-not-allowed rounded-lg border border-white/8 px-2 text-[11px] text-white/25"
          >
            天空蒙版
          </button>
        </div>
        <p id={splitHintId} className="text-[10px] leading-relaxed text-white/30">
          未接入真实的人物/天空分割模型，这两个蒙版暂不可用；请使用矩形或椭圆手动框选。
        </p>
      </div>

      {items.length === 0 ? (
        <p className="rounded-lg border border-dashed border-white/10 bg-black/20 px-3 py-4 text-[11px] leading-relaxed text-white/40">
          尚未添加局部调整。全图调整作用于整张画面；矩形/椭圆区域可单独提亮、压暗或调色。
        </p>
      ) : (
        <ul className="grid gap-3">
          {items.map((item, index) => {
            const mask = masksById.get(item.maskId) ?? null;
            const missing = item.maskId !== "full" && mask === null;
            const serverSkipped = renderWarnings.includes(
              `local_mask_missing:${item.maskId}`,
            );
            const expanded = activeId === item.id;
            const summary = missing
              ? "蒙版缺失"
              : mask
                ? mask.shape === "ellipse"
                  ? "椭圆"
                  : "矩形"
                : "全图";
            const localIsZero = LOCAL_V1_ADJUSTMENT_KEYS.every(
              (key) => (item.adjustments?.[key] ?? 0) === 0,
            );
            const maskVisible =
              !mask ||
              !geometry ||
              outlineOverlapsDisplay(maskOutlinePoints(mask, geometry.transform));

            return (
              <li key={item.id}>
                <div
                  className={`rounded-lg border ${
                    expanded ? "border-white/18 bg-black/20" : "border-white/8"
                  }`}
                >
                  <div className="flex flex-wrap items-center gap-2 p-2">
                    <button
                      type="button"
                      aria-expanded={expanded}
                      onClick={() => setSelectedId(item.id)}
                      className="min-h-9 flex-1 rounded-md px-1 text-left text-[11px] text-white/75 transition-colors hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                    >
                      局部 {index + 1} · {summary}
                      {mask?.inverted ? " · 反选" : ""}
                      {!item.enabled ? " · 已停用" : ""}
                      {serverSkipped && !missing ? " · 已跳过" : ""}
                    </button>
                    <label className="inline-flex items-center gap-1.5 text-[10px] text-white/55">
                      <input
                        type="checkbox"
                        checked={item.enabled}
                        disabled={disabled || missing}
                        aria-label={`启用局部 ${index + 1}`}
                        onChange={(event) =>
                          apply(
                            setLocalAdjustmentEnabled(
                              recipe,
                              item.id,
                              event.target.checked,
                            ),
                          )
                        }
                        className="size-3.5 accent-[#d8ff5f] disabled:opacity-40"
                      />
                      启用
                    </label>
                    <button
                      type="button"
                      aria-label={`删除局部 ${index + 1}`}
                      disabled={disabled}
                      onClick={() => apply(removeLocalAdjustment(recipe, item.id))}
                      className="min-h-9 rounded-md border border-white/10 px-2 text-[10px] text-white/55 transition-colors hover:bg-white/[0.06] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-35"
                    >
                      删除
                    </button>
                  </div>

                  {expanded && (
                    <div className="grid gap-3 border-t border-white/8 p-3">
                      {missing ? (
                        <div className="grid gap-2">
                          <p
                            role="alert"
                            className="rounded-md border border-amber-300/25 bg-amber-300/10 px-3 py-2 text-[11px] text-amber-100"
                          >
                            {serverSkipped
                              ? "服务器渲染已跳过此调整：引用的选区已不存在。"
                              : "蒙版缺失，已停用此局部调整。该蒙版可能来自旧数据或已被删除。"}
                          </p>
                          <button
                            type="button"
                            disabled={disabled}
                            onClick={() =>
                              apply(removeLocalAdjustment(recipe, item.id))
                            }
                            className="min-h-9 justify-self-start rounded-lg border border-amber-300/25 bg-amber-300/10 px-3 text-[11px] text-amber-100 transition-colors hover:bg-amber-300/20 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40"
                          >
                            删除该局部调整
                          </button>
                        </div>
                      ) : (
                        <>
                          {serverSkipped && (
                            <p
                              role="status"
                              className="rounded-md border border-amber-300/25 bg-amber-300/10 px-3 py-2 text-[11px] text-amber-100"
                            >
                              最近一次预览渲染已跳过此调整：请求时的选区引用已失效。
                            </p>
                          )}
                          <div
                            role="group"
                            aria-label="蒙版模式"
                            className="grid grid-cols-3 gap-1"
                          >
                            {MASK_MODES.map((mode) => {
                              const pressed =
                                mode.id === "full"
                                  ? item.maskId === "full"
                                  : mask?.shape === mode.id;
                              const modeDisabled =
                                disabled || (mode.id !== "full" && !mask && !canCreateMask);
                              return (
                                <button
                                  key={mode.id}
                                  type="button"
                                  aria-pressed={pressed}
                                  disabled={modeDisabled}
                                  onClick={() => switchMaskMode(item.id, mask, mode.id)}
                                  className={`min-h-9 rounded-md border px-1 text-[11px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-35 ${
                                    pressed
                                      ? "border-white/25 bg-white/10 text-white"
                                      : "border-white/10 bg-black/20 text-white/55 hover:bg-white/[0.06] hover:text-white"
                                  }`}
                                >
                                  {mode.label}
                                </button>
                              );
                            })}
                          </div>

                          {mask ? (
                            <>
                              <MaskCanvas
                                imageUrl={previewUrl}
                                previewWidth={previewWidth}
                                previewHeight={previewHeight}
                                rotationDeg={rotationDeg}
                                crop={crop}
                                sourceSize={sourceSize}
                                mask={mask}
                                disabled={disabled}
                                onChangeRegion={(region) => updateRegion(mask, region)}
                                onCommit={onCommit}
                              />
                              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                                <MaskPercentField
                                  label="区域左侧 x（%）"
                                  value={mask.x}
                                  min={0}
                                  max={100}
                                  disabled={disabled}
                                  onChange={(value) =>
                                    onChange(updateMask(recipe, mask.id, { x: value }))
                                  }
                                  onCommit={onCommit}
                                />
                                <MaskPercentField
                                  label="区域顶部 y（%）"
                                  value={mask.y}
                                  min={0}
                                  max={100}
                                  disabled={disabled}
                                  onChange={(value) =>
                                    onChange(updateMask(recipe, mask.id, { y: value }))
                                  }
                                  onCommit={onCommit}
                                />
                                <MaskPercentField
                                  label="区域宽度（%）"
                                  value={mask.width}
                                  min={1}
                                  max={100}
                                  disabled={disabled}
                                  onChange={(value) =>
                                    onChange(
                                      updateMask(recipe, mask.id, { width: value }),
                                    )
                                  }
                                  onCommit={onCommit}
                                />
                                <MaskPercentField
                                  label="区域高度（%）"
                                  value={mask.height}
                                  min={1}
                                  max={100}
                                  disabled={disabled}
                                  onChange={(value) =>
                                    onChange(
                                      updateMask(recipe, mask.id, { height: value }),
                                    )
                                  }
                                  onCommit={onCommit}
                                />
                              </div>
                              <div className="grid gap-4">
                                <SliderField
                                  label="局部羽化"
                                  value={mask.feather}
                                  min={MASK_RANGES.feather.min}
                                  max={MASK_RANGES.feather.max}
                                  step={MASK_RANGES.feather.step}
                                  defaultValue={MASK_RANGES.feather.defaultValue}
                                  disabled={disabled}
                                  onChange={(value) =>
                                    onChange(
                                      updateMask(recipe, mask.id, { feather: value }),
                                    )
                                  }
                                  onCommit={onCommit}
                                />
                                <SliderField
                                  label="局部不透明度"
                                  value={mask.opacity}
                                  min={MASK_RANGES.opacity.min}
                                  max={MASK_RANGES.opacity.max}
                                  step={MASK_RANGES.opacity.step}
                                  defaultValue={MASK_RANGES.opacity.defaultValue}
                                  disabled={disabled}
                                  onChange={(value) =>
                                    onChange(
                                      updateMask(recipe, mask.id, { opacity: value }),
                                    )
                                  }
                                  onCommit={onCommit}
                                />
                              </div>
                              <label className="inline-flex min-h-9 items-center gap-2 text-[11px] text-white/60">
                                <input
                                  type="checkbox"
                                  checked={mask.inverted}
                                  disabled={disabled}
                                  onChange={(event) =>
                                    apply(
                                      updateMask(recipe, mask.id, {
                                        inverted: event.target.checked,
                                      }),
                                    )
                                  }
                                  className="size-3.5 accent-[#d8ff5f] disabled:opacity-40"
                                />
                                反选蒙版（调整区域外）
                              </label>
                              {!maskVisible && (
                                <p className="text-[10px] leading-relaxed text-amber-200/80">
                                  当前裁切范围内看不到该蒙版，局部调整可能不会产生可见效果。
                                </p>
                              )}
                            </>
                          ) : (
                            <p className="text-[10px] leading-relaxed text-white/35">
                              全图局部调整会作用于整张画面。切换到矩形或椭圆可创建区域蒙版。
                            </p>
                          )}

                          <fieldset
                            disabled={disabled}
                            className="grid gap-4 border-t border-white/8 pt-3"
                          >
                            <legend className="px-1 font-mono text-[10px] uppercase tracking-[0.16em] text-white/40">
                              局部参数
                            </legend>
                            {LOCAL_FIELDS.map((field) => {
                              const range = ADJUSTMENT_RANGES[field.key];
                              return (
                                <SliderField
                                  key={field.key}
                                  label={field.label}
                                  value={item.adjustments?.[field.key] ?? 0}
                                  min={range.min}
                                  max={range.max}
                                  step={range.step}
                                  defaultValue={range.defaultValue}
                                  unit={field.unit}
                                  disabled={disabled}
                                  onChange={(value) =>
                                    onChange(
                                      updateLocalAdjustment(
                                        recipe,
                                        item.id,
                                        field.key,
                                        value,
                                      ),
                                    )
                                  }
                                  onCommit={onCommit}
                                />
                              );
                            })}
                          </fieldset>

                          <div className="flex flex-wrap gap-2">
                            <button
                              type="button"
                              disabled={disabled || localIsZero}
                              onClick={() => apply(resetLocalAdjustment(recipe, item.id))}
                              className="min-h-9 rounded-lg border border-white/12 px-2.5 text-[11px] text-white/60 transition-colors hover:bg-white/[0.06] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-35"
                            >
                              重置局部参数
                            </button>
                            <button
                              type="button"
                              disabled={disabled}
                              onClick={() => apply(removeLocalAdjustment(recipe, item.id))}
                              className="min-h-9 rounded-lg border border-white/12 px-2.5 text-[11px] text-white/55 transition-colors hover:bg-white/[0.05] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-35"
                            >
                              删除局部调整
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <p id={hintId} className="text-[10px] leading-relaxed text-white/30">
        蒙版锚定原图坐标（EXIF 方向归一化），旋转或裁切后仍跟随画面内容。羽化带位于区域内部，区域外不会被局部参数污染。
      </p>
    </section>
  );
}
