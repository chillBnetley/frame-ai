"use client";

import { originalImageUrl } from "@/lib/api/client";
import type {
  PersonalStyleAnalysisResponse,
  PersonalStyleReference,
  PersonalStyleReferenceContribution,
  PhotoVisualFeatures,
} from "@/types/personal-style";

import {
  ANALYSIS_STATUS_LABELS,
  FEATURE_CATEGORY_LABELS,
  FEATURE_ORIGIN_LABELS,
  formatPercent,
  sceneLabel,
} from "../presentation";

function statusTone(status: string): string {
  switch (status) {
    case "completed":
      return "border-[#c4ddcf] bg-[#f1f8f4] text-[#25624f]";
    case "failed":
      return "border-[#efc9c4] bg-[#fdf4f2] text-[#8a3a2e]";
    case "missing":
      return "border-[#e4e8e5] bg-[#f7f9f7] text-[#8a9690]";
    case "pending":
    case "processing":
      return "border-[#eadfc4] bg-[#fbf7ec] text-[#7b6228]";
    default:
      return "border-[#dbe5e0] bg-[#f4f8f6] text-[#365148]";
  }
}

function FeatureDetails({ features }: { features: PhotoVisualFeatures }) {
  const groups = new Map<string, PhotoVisualFeatures["readings"][number][]>();
  for (const reading of features.readings) {
    const list = groups.get(reading.category) ?? [];
    list.push(reading);
    groups.set(reading.category, list);
  }
  return (
    <div className="mt-3 rounded-xl border border-[#e4e8e5] bg-[#fbfcfa] p-3">
      <div className="flex flex-wrap items-center gap-2 text-[10px] text-[#7a8680]">
        <span className="rounded-full bg-white px-2 py-0.5 font-medium text-[#4a574f]">
          分析版本 {features.extractorVersion}
        </span>
        <span>整体置信度 {formatPercent(features.overallConfidence)}</span>
        {features.isMock && (
          <span className="rounded-full border border-[#eadfc4] bg-[#fbf7ec] px-2 py-0.5 text-[#7b6228]">
            模拟分析
          </span>
        )}
      </div>
      <div className="mt-3 space-y-3">
        {Array.from(groups.entries()).map(([category, readings]) => (
          <div key={category}>
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#8a9a93]">
              {FEATURE_CATEGORY_LABELS[category] ?? category}
            </p>
            <ul className="mt-1.5 space-y-1.5">
              {readings.map((reading) => (
                <li
                  key={`${reading.category}:${reading.key}`}
                  className="rounded-lg border border-[#eef1ef] bg-white px-2.5 py-2"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-[11px] font-medium text-[#3b4841]">
                      {reading.label}
                    </span>
                    <div className="flex items-center gap-1.5 text-[9px]">
                      <span className="rounded-full bg-[#f2f6f3] px-1.5 py-0.5 text-[#6b7a73]">
                        {FEATURE_ORIGIN_LABELS[reading.origin] ?? reading.origin}
                      </span>
                      <span
                        className={`rounded-full px-1.5 py-0.5 ${
                          reading.editable
                            ? "bg-[#f0f7f4] text-[#277a68]"
                            : "bg-[#f7f9f7] text-[#8a9690]"
                        }`}
                      >
                        {reading.editable ? "可修改" : "只读"}
                      </span>
                    </div>
                  </div>
                  <p className="mt-1 text-[11px] leading-relaxed text-[#66716b]">
                    {reading.description}
                  </p>
                  {reading.evidence.length > 0 && (
                    <p className="mt-1 font-mono text-[9px] text-[#9aa5a0]">
                      {reading.evidence.join(" · ")}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      {features.anomalies.length > 0 && (
        <div className="mt-3 rounded-lg border border-[#f0e0c5] bg-[#fdfaf3] px-3 py-2">
          <p className="text-[10px] font-semibold text-[#8a6228]">不确定性与异常</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[10px] leading-relaxed text-[#8a6f45]">
            {features.anomalies.map((anomaly) => (
              <li key={anomaly.code}>{anomaly.message}</li>
            ))}
          </ul>
        </div>
      )}
      {features.limitations.length > 0 && (
        <ul className="mt-2 list-disc space-y-0.5 pl-4 text-[10px] leading-relaxed text-[#8a9690]">
          {features.limitations.map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function ReferenceAnalysisPanel({
  references,
  analysis,
  features,
  featuresLoadingId,
  contributions,
  busy,
  error,
  onToggleFeatures,
  onRemoveReference,
  onAnalyze,
  onAnalyzeReference,
  onFuse,
}: {
  references: PersonalStyleReference[];
  analysis: PersonalStyleAnalysisResponse | null;
  features: Record<string, PhotoVisualFeatures>;
  featuresLoadingId: string | null;
  contributions: PersonalStyleReferenceContribution[];
  busy: "analyze" | "fuse" | null;
  error: string | null;
  onToggleFeatures: (referenceId: string) => void;
  onRemoveReference: (reference: PersonalStyleReference) => void;
  onAnalyze: () => void;
  onAnalyzeReference: (referenceId: string) => void;
  onFuse: () => void;
}) {
  const analysisById = new Map(
    (analysis?.references ?? []).map((item) => [item.referenceId, item]),
  );
  const contributionById = new Map(
    contributions.map((item) => [item.referenceId, item]),
  );
  const completed = analysis?.completedCount ?? 0;
  const hasCompleted = completed > 0;
  const running = (analysis?.references ?? []).some(
    (item) => item.status === "pending" || item.status === "processing",
  );

  return (
    <section aria-labelledby="analysis-heading" className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-[#8a9a93]">
            REFERENCE ANALYSIS
          </p>
          <h2 id="analysis-heading" className="mt-1 text-xl font-semibold tracking-[-0.03em] text-[#1d2521]">
            参考照片与特征
          </h2>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy !== null || references.length === 0}
            onClick={onAnalyze}
            className="inline-flex min-h-10 items-center rounded-xl border border-[#d7dfda] bg-white px-4 text-xs font-medium text-[#2775a0] hover:bg-[#f4f8fb] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50"
          >
            {busy === "analyze"
              ? "正在启动分析…"
              : hasCompleted || running
                ? "重新分析全部"
                : "开始分析"}
          </button>
          <button
            type="button"
            disabled={busy !== null || !hasCompleted}
            onClick={onFuse}
            className="inline-flex min-h-10 items-center rounded-xl bg-[#277a68] px-4 text-xs font-medium text-white shadow-[0_10px_24px_-16px_rgba(39,122,104,0.8)] hover:bg-[#206557] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy === "fuse" ? "正在融合…" : "生成个人风格"}
          </button>
        </div>
      </div>

      {analysis !== null && (
        <p className="text-[11px] text-[#8a9690]">
          已完成 {completed} / {analysis.totalCount} 张。分析状态来自真实任务进度。
          {hasCompleted && " 完成分析后可以生成或更新风格版本。"}
          重新分析不会删除旧版本，用户手动确认的字段也不会被静默覆盖。
          撤回授权会删除该照片的提取特征，但会保留你的原始图片。
        </p>
      )}

      {error !== null && (
        <div role="alert" className="rounded-xl border border-[#efc9c4] bg-[#fdf4f2] px-4 py-3 text-xs text-[#8a3a2e]">
          {error}
        </div>
      )}

      {references.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[#cfd9d3] bg-[#f8faf8] px-4 py-6 text-center text-xs text-[#7a8680]">
          还没有参考照片。请在下方添加照片后再开始分析。
        </div>
      ) : (
        <ul className="space-y-2">
          {references.map((reference) => {
            const item = analysisById.get(reference.id);
            const feature = features[reference.id];
            const contribution = contributionById.get(reference.id);
            const status = item?.status ?? "analysis_required";
            const imageId = reference.imageId;
            return (
              <li
                key={reference.id}
                className="rounded-xl border border-[#dfe5e1] bg-white p-3"
              >
                <div className="flex flex-wrap items-start gap-3">
                  {imageId != null ? (
                    // eslint-disable-next-line @next/next/no-img-element -- local originals are served by the API
                    <img
                      src={originalImageUrl(imageId)}
                      alt=""
                      className="size-16 rounded-lg object-cover"
                    />
                  ) : (
                    <div className="grid size-16 place-items-center rounded-lg bg-[#f2f5f3] text-[10px] text-[#9aa5a0]">
                      已删除
                    </div>
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="max-w-full truncate text-xs font-medium text-[#2a3530]">
                        {reference.originalName}
                      </p>
                      <span
                        className={`rounded-full border px-2 py-0.5 text-[9px] font-medium ${statusTone(status)}`}
                      >
                        {ANALYSIS_STATUS_LABELS[status] ?? status}
                      </span>
                      {feature !== undefined && (
                        <span className="text-[9px] text-[#8a9690]">
                          {sceneLabel(feature.scene.primary)} · 置信度 {formatPercent(feature.overallConfidence)}
                        </span>
                      )}
                      {contribution !== undefined && (
                        <span className="text-[9px] text-[#6b7a73]">
                          融合权重 {formatPercent(contribution.weight)}
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-[10px] text-[#8a9690]">
                      授权范围：仅用于本风格分析 · 授权于{" "}
                      {new Date(reference.consentAt).toLocaleDateString("zh-CN")}
                      {reference.status === "removed" ? " · 授权已撤回" : ""}
                      {item?.error ? ` · ${item.error}` : ""}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {item?.featureAvailable === true && (
                        <button
                          type="button"
                          onClick={() => onToggleFeatures(reference.id)}
                          aria-expanded={feature !== undefined}
                          className="inline-flex min-h-8 items-center rounded-lg border border-[#d7dfda] bg-white px-2.5 text-[10px] font-medium text-[#277a68] hover:bg-[#f4f8f6] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                        >
                          {featuresLoadingId === reference.id
                            ? "加载中…"
                            : feature !== undefined
                              ? "收起特征"
                              : "查看特征"}
                        </button>
                      )}
                      {imageId != null && (
                        <button
                          type="button"
                          disabled={busy !== null}
                          onClick={() => onAnalyzeReference(reference.id)}
                          className="inline-flex min-h-8 items-center rounded-lg border border-[#d7dfda] bg-white px-2.5 text-[10px] font-medium text-[#2775a0] hover:bg-[#f4f8fb] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50"
                        >
                          重新分析
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => onRemoveReference(reference)}
                        className="inline-flex min-h-8 items-center rounded-lg px-2.5 text-[10px] font-medium text-[#8a3a2e] hover:bg-[#fdf4f2] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                      >
                        撤回授权
                      </button>
                    </div>
                  </div>
                </div>
                {feature !== undefined && <FeatureDetails features={feature} />}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
