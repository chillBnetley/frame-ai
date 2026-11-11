"use client";

import { useId } from "react";

import type { GenerativeCapabilitiesResponse } from "@/types/generative";
import type { StudioBaseLayer, StudioCapability, StudioCompareMode } from "./use-studio-state";

export interface StudioCapabilityMeta {
  value: StudioCapability;
  label: string;
  short: string;
  hint: string;
}

export const STUDIO_CAPABILITIES: StudioCapabilityMeta[] = [
  {
    value: "outpaint",
    label: "AI 画幅扩充",
    short: "扩图",
    hint: "向外扩展构图，原图区域保持字节级一致。",
  },
  {
    value: "remove",
    label: "AI 智能消除",
    short: "消除",
    hint: "涂抹要移除的对象，AI 修复背景，保护区不变。",
  },
  {
    value: "local_edit",
    label: "AI 局部生成",
    short: "局部",
    hint: "圈选区域并用自然语言描述改动，其余像素保留。",
  },
];

const BASE_LAYERS: { value: StudioBaseLayer; label: string }[] = [
  { value: "current", label: "当前版本" },
  { value: "original", label: "原始照片" },
];

const COMPARE_MODES: { value: StudioCompareMode; label: string }[] = [
  { value: "off", label: "关闭" },
  { value: "slider", label: "滑动对比" },
  { value: "side", label: "并排对比" },
];

export interface StudioToolRailProps {
  capability: StudioCapability;
  capabilities: GenerativeCapabilitiesResponse | null;
  onCapabilityChange: (capability: StudioCapability) => void;
  baseLayer: StudioBaseLayer;
  onBaseLayerChange: (baseLayer: StudioBaseLayer) => void;
  resultVisible: boolean;
  onResultVisibleChange: (resultVisible: boolean) => void;
  maskOverlayVisible: boolean;
  onToggleMaskOverlay: () => void;
  maskRequired: boolean;
  compare: StudioCompareMode;
  onCompareChange: (compare: StudioCompareMode) => void;
  hasResult: boolean;
  scale: number;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFitToWindow: () => void;
  onResetScale: () => void;
  disabled?: boolean;
}

const sectionClass = "flex flex-col gap-2";
const headingClass = "text-[11px] font-medium uppercase tracking-[0.12em] text-neutral-400";
const choiceClass =
  "w-full px-3 py-2 text-left text-xs rounded-lg border transition-all disabled:cursor-not-allowed disabled:opacity-45";
const choiceActiveClass =
  "bg-sky-950/60 border-sky-500/70 text-white ring-1 ring-sky-500/40";
const choiceIdleClass =
  "bg-neutral-950/50 border-neutral-800 text-neutral-300 hover:border-neutral-700 hover:bg-neutral-900";

export function StudioToolRail({
  capability,
  capabilities,
  onCapabilityChange,
  baseLayer,
  onBaseLayerChange,
  resultVisible,
  onResultVisibleChange,
  maskOverlayVisible,
  onToggleMaskOverlay,
  maskRequired,
  compare,
  onCompareChange,
  hasResult,
  scale,
  onZoomIn,
  onZoomOut,
  onFitToWindow,
  onResetScale,
  disabled = false,
}: StudioToolRailProps) {
  const railId = useId();
  const activeMeta = STUDIO_CAPABILITIES.find((item) => item.value === capability);

  const isSupported = (value: StudioCapability): boolean =>
    capabilities === null || capabilities.supportedTaskTypes.includes(value);

  return (
    <div
      aria-label="创意工作台工具区"
      className="flex flex-col gap-5 p-4 rounded-xl border border-neutral-800 bg-neutral-900 text-neutral-100"
    >
      <div className={sectionClass}>
        <h3 id={`${railId}-capability`} className={headingClass}>
          生成能力
        </h3>
        <div role="radiogroup" aria-labelledby={`${railId}-capability`} className="flex flex-col gap-1.5">
          {STUDIO_CAPABILITIES.map((item) => {
            const supported = isSupported(item.value);
            return (
              <button
                key={item.value}
                type="button"
                role="radio"
                aria-checked={item.value === capability}
                disabled={disabled || !supported}
                title={supported ? item.hint : "当前 Provider 不支持该任务类型"}
                onClick={() => onCapabilityChange(item.value)}
                className={`${choiceClass} ${item.value === capability ? choiceActiveClass : choiceIdleClass}`}
              >
                <span className="block font-medium">{item.label}</span>
                <span className="mt-0.5 block text-[11px] text-neutral-400">{item.hint}</span>
              </button>
            );
          })}
        </div>
        {capabilities?.isMock && (
          <p className="text-[11px] text-amber-300">模拟生成模式：结果由 Mock Provider 产出。</p>
        )}
      </div>

      <div className={sectionClass}>
        <h3 id={`${railId}-base`} className={headingClass}>
          底图图层
        </h3>
        <div role="radiogroup" aria-labelledby={`${railId}-base`} className="flex gap-1.5">
          {BASE_LAYERS.map((item) => (
            <button
              key={item.value}
              type="button"
              role="radio"
              aria-checked={item.value === baseLayer}
              disabled={disabled}
              onClick={() => onBaseLayerChange(item.value)}
              className={`flex-1 px-2 py-1.5 text-center ${choiceClass} ${
                item.value === baseLayer ? choiceActiveClass : choiceIdleClass
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
        <button
          type="button"
          aria-pressed={resultVisible}
          disabled={disabled || !hasResult}
          title={hasResult ? undefined : "生成候选就绪后可用"}
          onClick={() => onResultVisibleChange(!resultVisible)}
          className={`${choiceClass} ${
            resultVisible && hasResult ? choiceActiveClass : choiceIdleClass
          }`}
        >
          {hasResult
            ? resultVisible
              ? "结果预览：显示 AI 候选"
              : "结果预览：已隐藏，仅看底图"
            : "结果预览：等待候选"}
        </button>
      </div>

      <div className={sectionClass}>
        <h3 className={headingClass}>蒙版显示</h3>
        <button
          type="button"
          aria-pressed={maskOverlayVisible}
          disabled={disabled || !maskRequired}
          onClick={onToggleMaskOverlay}
          className={`${choiceClass} ${
            maskOverlayVisible && maskRequired ? choiceActiveClass : choiceIdleClass
          }`}
        >
          {maskRequired
            ? maskOverlayVisible
              ? "蒙版选区：高亮显示中"
              : "蒙版选区：已隐藏"
            : "该能力不需要蒙版"}
        </button>
      </div>

      <div className={sectionClass}>
        <h3 id={`${railId}-compare`} className={headingClass}>
          前后对比
        </h3>
        <div role="radiogroup" aria-labelledby={`${railId}-compare`} className="flex flex-col gap-1.5">
          {COMPARE_MODES.map((item) => (
            <button
              key={item.value}
              type="button"
              role="radio"
              aria-checked={item.value === compare}
              disabled={disabled || !hasResult}
              title={hasResult ? undefined : "生成候选就绪后可用"}
              onClick={() => onCompareChange(item.value)}
              className={`px-2 py-1.5 text-center ${choiceClass} ${
                item.value === compare ? choiceActiveClass : choiceIdleClass
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div className={sectionClass}>
        <h3 className={headingClass}>画布视图</h3>
        <div className="grid grid-cols-3 gap-1.5">
          <button
            type="button"
            onClick={onZoomOut}
            disabled={disabled}
            aria-label="缩小画布"
            className={`px-2 py-1.5 text-center ${choiceClass} ${choiceIdleClass}`}
          >
            −
          </button>
          <button
            type="button"
            onClick={onResetScale}
            disabled={disabled}
            aria-label="恢复 100% 显示"
            className={`px-2 py-1.5 text-center font-mono ${choiceClass} ${choiceIdleClass}`}
          >
            {Math.round(scale * 100)}%
          </button>
          <button
            type="button"
            onClick={onZoomIn}
            disabled={disabled}
            aria-label="放大画布"
            className={`px-2 py-1.5 text-center ${choiceClass} ${choiceIdleClass}`}
          >
            +
          </button>
        </div>
        <button
          type="button"
          onClick={onFitToWindow}
          disabled={disabled}
          className={`px-2 py-1.5 text-center ${choiceClass} ${choiceIdleClass}`}
        >
          适应窗口
        </button>
        <p className="text-[11px] leading-relaxed text-neutral-500">
          画布内：滚轮缩放、拖动或方向键平移、双指区域无需额外模式。
        </p>
      </div>

      {activeMeta && (
        <p className="text-[11px] leading-relaxed text-neutral-400 border-t border-neutral-800 pt-3">
          当前：{activeMeta.label}
        </p>
      )}
    </div>
  );
}
