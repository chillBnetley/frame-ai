"use client";

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

const groupLabelClass = "text-[11px] text-[#8a938e]";
const chipClass =
  "min-h-9 rounded-lg border px-2.5 text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-45";
const chipActiveClass = "border-[#277a68] bg-[#277a68] font-semibold text-[#ffffff]";
const chipIdleClass =
  "border-[#dfe4e0] bg-[#ffffff] text-[#3d4541] hover:border-[#c3cec8] hover:bg-[#eef1ef]";

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
  const resultLabel = hasResult
    ? resultVisible
      ? "结果预览：显示 AI 候选"
      : "结果预览：已隐藏，仅看底图"
    : "结果预览：等待候选";
  const maskLabel = maskRequired
    ? maskOverlayVisible
      ? "蒙版选区：高亮显示中"
      : "蒙版选区：已隐藏"
    : "该能力不需要蒙版";

  const isSupported = (value: StudioCapability): boolean =>
    capabilities === null || capabilities.supportedTaskTypes.includes(value);

  return (
    <div
      aria-label="创意工作台工具区"
      className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-[#e4e8e5] bg-[#f6f7f6] px-3 py-2"
    >
      <div role="radiogroup" aria-label="生成能力" className="flex flex-wrap gap-1.5">
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
              className={`${chipClass} ${
                item.value === capability ? chipActiveClass : chipIdleClass
              }`}
            >
              {item.label}
            </button>
          );
        })}
      </div>

      <div className="flex items-center gap-1.5">
        <span className={groupLabelClass}>底图</span>
        <div role="radiogroup" aria-label="底图图层" className="flex gap-1.5">
          {BASE_LAYERS.map((item) => (
            <button
              key={item.value}
              type="button"
              role="radio"
              aria-checked={item.value === baseLayer}
              disabled={disabled}
              onClick={() => onBaseLayerChange(item.value)}
              className={`${chipClass} ${
                item.value === baseLayer ? chipActiveClass : chipIdleClass
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-1.5">
        <button
          type="button"
          aria-label={resultLabel}
          aria-pressed={resultVisible && hasResult}
          disabled={disabled || !hasResult}
          title={resultLabel}
          onClick={() => onResultVisibleChange(!resultVisible)}
          className={`${chipClass} ${
            resultVisible && hasResult ? chipActiveClass : chipIdleClass
          }`}
        >
          {hasResult ? "候选" : "等待候选"}
        </button>
        <button
          type="button"
          aria-label={maskLabel}
          aria-pressed={maskOverlayVisible && maskRequired}
          disabled={disabled || !maskRequired}
          title={maskLabel}
          onClick={onToggleMaskOverlay}
          className={`${chipClass} ${
            maskOverlayVisible && maskRequired ? chipActiveClass : chipIdleClass
          }`}
        >
          蒙版
        </button>
      </div>

      <div className="flex items-center gap-1.5">
        <span className={groupLabelClass}>对比</span>
        <div role="radiogroup" aria-label="前后对比" className="flex gap-1.5">
          {COMPARE_MODES.map((item) => (
            <button
              key={item.value}
              type="button"
              role="radio"
              aria-checked={item.value === compare}
              disabled={disabled || !hasResult}
              title={hasResult ? undefined : "生成候选就绪后可用"}
              onClick={() => onCompareChange(item.value)}
              className={`${chipClass} ${
                item.value === compare ? chipActiveClass : chipIdleClass
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div className="ml-auto flex items-center gap-1.5">
        <button
          type="button"
          onClick={onZoomOut}
          disabled={disabled}
          aria-label="缩小画布"
          className={`${chipClass} ${chipIdleClass}`}
        >
          −
        </button>
        <button
          type="button"
          onClick={onResetScale}
          disabled={disabled}
          aria-label="恢复 100% 显示"
          className={`${chipClass} ${chipIdleClass} w-16 font-mono`}
        >
          {Math.round(scale * 100)}%
        </button>
        <button
          type="button"
          onClick={onZoomIn}
          disabled={disabled}
          aria-label="放大画布"
          className={`${chipClass} ${chipIdleClass}`}
        >
          +
        </button>
        <button
          type="button"
          onClick={onFitToWindow}
          disabled={disabled}
          className={`${chipClass} ${chipIdleClass}`}
        >
          适应窗口
        </button>
      </div>
    </div>
  );
}
