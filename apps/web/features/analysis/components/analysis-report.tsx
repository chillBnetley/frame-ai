"use client";

import { useState } from "react";

import type {
  AnalysisIssue,
  AnalysisReport,
  AnalysisRecommendation,
  IssueSeverity,
  RecommendationPriority,
} from "@/types/analysis";

import {
  balanceLabel,
  categoryLabel,
  contrastLabel,
  harmonyLabel,
  issueTypeLabel,
  lightingDirectionLabel,
  lightingTypeLabel,
  negativeSpaceLabel,
  occlusionLabel,
  PRIORITY_LABELS,
  relatedIssueLabels,
  saturationLabel,
  sceneLabel,
  SEVERITY_LABELS,
  sortIssues,
  sortRecommendations,
  subjectPositionLabel,
  subjectRoleLabel,
  subjectTypeLabel,
  temperatureLabel,
} from "../presentation";
import { SubjectOverlay } from "./subject-overlay";

const SEVERITY_STYLES: Record<IssueSeverity, string> = {
  high: "border-red-300/30 bg-red-300/10 text-red-200",
  medium: "border-amber-300/30 bg-amber-300/10 text-amber-100",
  low: "border-white/12 bg-white/[0.04] text-white/60",
};

const PRIORITY_STYLES: Record<RecommendationPriority, string> = {
  high: "border-accent/30 bg-accent/10 text-accent",
  medium: "border-amber-300/25 bg-amber-300/[0.07] text-amber-100",
  low: "border-white/12 bg-white/[0.04] text-white/60",
};

function formatConfidence(value: number): string {
  return `${Math.round(Math.min(Math.max(value, 0), 1) * 100)}%`;
}

function formatRatio(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "未评估";
  }
  return formatConfidence(value);
}

function formatTilt(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "未检测";
  }
  return `${value.toFixed(1)}°`;
}

function formatBBox(box: {
  x: number;
  y: number;
  width: number;
  height: number;
}): string {
  const percent = (value: number) => `${Math.round(value * 100)}%`;
  return `位置 (${percent(box.x)}, ${percent(box.y)}) · 尺寸 ${percent(box.width)} × ${percent(box.height)}`;
}

function SectionHeading({
  id,
  children,
}: {
  id: string;
  children: string;
}) {
  return (
    <h4 id={id} className="text-xs font-semibold tracking-wide text-white">
      {children}
    </h4>
  );
}

function IssueItem({ issue }: { issue: AnalysisIssue }) {
  return (
    <li className="rounded-lg border border-white/8 bg-white/[0.02] px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-white">
          {issueTypeLabel(issue.type)}
        </span>
        <span
          className={`rounded-full border px-2 py-0.5 text-[10px] ${SEVERITY_STYLES[issue.severity]}`}
        >
          严重度 {SEVERITY_LABELS[issue.severity]}
        </span>
        <span className="font-mono text-[10px] text-white/40">
          置信度 {formatConfidence(issue.confidence)}
        </span>
      </div>
      <details className="mt-1">
        <summary className="cursor-pointer text-[11px] text-white/50 hover:text-white/70">
          查看分析依据
        </summary>
        <p className="mt-1 text-[11px] leading-relaxed text-white/60">
          {issue.evidence}
        </p>
      </details>
      {issue.suggestion && (
        <p className="mt-1 text-[11px] leading-relaxed text-white/70">
          <span className="text-white/40">建议：</span>
          {issue.suggestion}
        </p>
      )}
      {issue.regionIds.length > 0 && (
        <p className="mt-1 flex flex-wrap gap-1">
          {issue.regionIds.map((regionId) => (
            <span
              key={regionId}
              className="rounded border border-white/10 px-1.5 py-0.5 font-mono text-[9px] text-white/45"
            >
              {regionId}
            </span>
          ))}
        </p>
      )}
    </li>
  );
}

function RecommendationItem({
  recommendation,
  issues,
}: {
  recommendation: AnalysisRecommendation;
  issues: readonly AnalysisIssue[];
}) {
  const related = relatedIssueLabels(recommendation, issues);
  return (
    <li className="rounded-lg border border-white/8 bg-white/[0.02] px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`rounded-full border px-2 py-0.5 text-[10px] ${PRIORITY_STYLES[recommendation.priority]}`}
        >
          {PRIORITY_LABELS[recommendation.priority]}
        </span>
        <span className="text-[10px] text-white/45">
          {categoryLabel(recommendation.category)}
        </span>
      </div>
      <p className="mt-1 text-[11px] leading-relaxed text-white/70">
        {recommendation.description}
      </p>
      <p className="mt-1 text-[10px] text-white/40">
        {related.length > 0
          ? `对应问题：${related.join("、")}`
          : recommendation.targetRegions.length > 0
            ? "对应问题：相关区域"
            : "适用于整张照片"}
      </p>
      {recommendation.targetRegions.length > 0 && (
        <p className="mt-1 flex flex-wrap gap-1">
          {recommendation.targetRegions.map((regionId) => (
            <span
              key={regionId}
              className="rounded border border-white/10 px-1.5 py-0.5 font-mono text-[9px] text-white/45"
            >
              {regionId}
            </span>
          ))}
        </p>
      )}
    </li>
  );
}

export interface AnalysisReportViewProps {
  imageId: string;
  report: AnalysisReport;
}

export function AnalysisReportView({
  imageId,
  report,
}: AnalysisReportViewProps) {
  const [showOverlay, setShowOverlay] = useState(false);
  const issues = sortIssues(report.issues);
  const recommendations = sortRecommendations(report.recommendations);
  const hasSubjects = report.subjects.length > 0;

  return (
    <div className="grid gap-4">
      <section
        aria-labelledby="analysis-scene-heading"
        className="rounded-xl border border-white/8 bg-white/[0.02] p-3"
      >
        <SectionHeading id="analysis-scene-heading">场景识别</SectionHeading>
        <dl className="mt-2 grid grid-cols-2 gap-2 text-[11px]">
          <div>
            <dt className="text-white/40">主场景</dt>
            <dd className="mt-0.5 text-white/75">
              {sceneLabel(report.scene.primary)}
            </dd>
          </div>
          <div>
            <dt className="text-white/40">置信度</dt>
            <dd className="mt-0.5 font-mono text-white/75">
              {formatConfidence(report.scene.confidence)}
            </dd>
          </div>
        </dl>
        <p className="mt-2 text-[11px] text-white/50">
          次要场景：
          {report.scene.secondary.length > 0
            ? report.scene.secondary.map(sceneLabel).join("、")
            : "无"}
        </p>
      </section>

      <section
        aria-labelledby="analysis-subjects-heading"
        className="rounded-xl border border-white/8 bg-white/[0.02] p-3"
      >
        <div className="flex items-start justify-between gap-2">
          <SectionHeading id="analysis-subjects-heading">
            主体识别
          </SectionHeading>
          {hasSubjects && (
            <button
              type="button"
              aria-pressed={showOverlay}
              onClick={() => setShowOverlay((value) => !value)}
              className="min-h-11 rounded-lg border border-white/12 bg-white/[0.03] px-3 text-[11px] text-white/65 transition-colors hover:bg-white/[0.07] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              {showOverlay ? "隐藏主体框" : "显示主体框"}
            </button>
          )}
        </div>
        {hasSubjects ? (
          <>
            <ul className="mt-2 grid gap-2">
              {report.subjects.map((subject) => (
                <li
                  key={subject.id}
                  className="rounded-lg border border-white/8 px-2.5 py-2"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[11px] font-medium text-white/80">
                      {subjectTypeLabel(subject.type)}
                    </span>
                    <span className="rounded-full border border-white/10 px-2 py-0.5 text-[10px] text-white/50">
                      {subjectRoleLabel(subject.role)}
                    </span>
                    <span className="font-mono text-[10px] text-white/40">
                      置信度 {formatConfidence(subject.confidence)}
                    </span>
                  </div>
                  <p className="mt-1 font-mono text-[10px] text-white/40">
                    {formatBBox(subject.bbox)}
                  </p>
                  <p className="mt-0.5 font-mono text-[9px] text-white/30">
                    区域 {subject.regionId}
                  </p>
                </li>
              ))}
            </ul>
            {showOverlay && (
              <div className="mt-3">
                <SubjectOverlay
                  imageId={imageId}
                  imageWidth={report.image.width}
                  imageHeight={report.image.height}
                  subjects={report.subjects}
                />
              </div>
            )}
            <div className="mt-3">
              <p className="text-[11px] text-white/45">
                区域列表（{report.regions.length}）
              </p>
              {report.regions.length > 0 ? (
                <ul className="mt-1 grid gap-1">
                  {report.regions.map((region) => (
                    <li
                      key={region.id}
                      className="flex flex-wrap items-center justify-between gap-2 rounded border border-white/8 px-2 py-1 font-mono text-[10px] text-white/45"
                    >
                      <span>{region.id}</span>
                      <span>{subjectTypeLabel(region.type)}</span>
                      <span>{formatBBox(region.bbox)}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-1 text-[11px] text-white/35">没有可用区域。</p>
              )}
            </div>
          </>
        ) : (
          <p className="mt-2 text-[11px] text-white/45">
            未识别到明确主体，未生成主体框。
          </p>
        )}
        <div className="mt-3 border-t border-white/8 pt-3">
          <h5 className="text-[11px] font-semibold text-white/70">
            构图与遮挡
          </h5>
          <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-2 text-[11px]">
            <div>
              <dt className="text-white/40">构图平衡</dt>
              <dd className="mt-0.5 text-white/75">
                {balanceLabel(report.composition.balance)}
              </dd>
            </div>
            <div>
              <dt className="text-white/40">主体位置</dt>
              <dd className="mt-0.5 text-white/75">
                {subjectPositionLabel(report.composition.subjectPosition)}
              </dd>
            </div>
            <div>
              <dt className="text-white/40">负空间</dt>
              <dd className="mt-0.5 text-white/75">
                {negativeSpaceLabel(report.composition.negativeSpace)}
              </dd>
            </div>
            <div>
              <dt className="text-white/40">遮挡</dt>
              <dd className="mt-0.5 text-white/75">
                {occlusionLabel(report.composition.occlusion)}
              </dd>
            </div>
            <div>
              <dt className="text-white/40">主体占比</dt>
              <dd className="mt-0.5 font-mono text-white/75">
                {formatRatio(report.composition.subjectAreaRatio)}
              </dd>
            </div>
            <div>
              <dt className="text-white/40">地平线倾斜</dt>
              <dd className="mt-0.5 font-mono text-white/75">
                {formatTilt(report.composition.horizonTiltDeg)}
              </dd>
            </div>
          </dl>
        </div>
      </section>

      <section
        aria-labelledby="analysis-light-heading"
        className="rounded-xl border border-white/8 bg-white/[0.02] p-3"
      >
        <SectionHeading id="analysis-light-heading">光线与色彩</SectionHeading>
        <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-2 text-[11px]">
          <div>
            <dt className="text-white/40">光线方向</dt>
            <dd className="mt-0.5 text-white/75">
              {lightingDirectionLabel(report.lighting.direction)}
            </dd>
          </div>
          <div>
            <dt className="text-white/40">光线类型</dt>
            <dd className="mt-0.5 text-white/75">
              {lightingTypeLabel(report.lighting.type)}
            </dd>
          </div>
          <div>
            <dt className="text-white/40">反差</dt>
            <dd className="mt-0.5 text-white/75">
              {contrastLabel(report.lighting.contrast)}
            </dd>
          </div>
          <div>
            <dt className="text-white/40">色彩冷暖</dt>
            <dd className="mt-0.5 text-white/75">
              {temperatureLabel(report.color.temperature)}
            </dd>
          </div>
          <div>
            <dt className="text-white/40">饱和度</dt>
            <dd className="mt-0.5 text-white/75">
              {saturationLabel(report.color.saturation)}
            </dd>
          </div>
          <div>
            <dt className="text-white/40">色彩协调</dt>
            <dd className="mt-0.5 text-white/75">
              {harmonyLabel(report.color.harmony)}
            </dd>
          </div>
          <div>
            <dt className="text-white/40">分析置信度</dt>
            <dd className="mt-0.5 font-mono text-white/75">
              {formatConfidence(
                Math.min(report.lighting.confidence, report.color.confidence),
              )}
            </dd>
          </div>
        </dl>
        <div className="mt-2">
          <p className="text-[10px] text-white/40">主色</p>
          {report.color.dominantColors.length > 0 ? (
            <ul className="mt-1 flex flex-wrap gap-1.5">
              {report.color.dominantColors.map((color) => (
                <li
                  key={color}
                  className="inline-flex items-center gap-1 rounded-full border border-white/10 px-2 py-0.5 font-mono text-[9px] text-white/55"
                >
                  <span
                    aria-hidden="true"
                    className="size-2.5 rounded-full border border-white/20"
                    style={{ backgroundColor: color }}
                  />
                  {color}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-[11px] text-white/35">未提供主色。</p>
          )}
        </div>
      </section>

      <section
        aria-labelledby="analysis-issues-heading"
        className="rounded-xl border border-white/8 bg-white/[0.02] p-3"
      >
        <SectionHeading id="analysis-issues-heading">摄影问题</SectionHeading>
        {issues.length > 0 ? (
          <ol className="mt-2 grid gap-2">
            {issues.map((issue) => (
              <IssueItem key={issue.id} issue={issue} />
            ))}
          </ol>
        ) : (
          <p className="mt-2 text-[11px] text-white/45">
            未发现明确的摄影问题。
          </p>
        )}
      </section>

      <section
        aria-labelledby="analysis-recommendations-heading"
        className="rounded-xl border border-white/8 bg-white/[0.02] p-3"
      >
        <SectionHeading id="analysis-recommendations-heading">
          AI 摄影建议
        </SectionHeading>
        {recommendations.length > 0 ? (
          <ol className="mt-2 grid gap-2">
            {recommendations.map((recommendation, index) => (
              <RecommendationItem
                key={`${recommendation.category}-${index}`}
                recommendation={recommendation}
                issues={issues}
              />
            ))}
          </ol>
        ) : (
          <p className="mt-2 text-[11px] text-white/45">暂无可执行建议。</p>
        )}
      </section>

      <section
        aria-labelledby="analysis-limitations-heading"
        className="rounded-xl border border-amber-300/20 bg-amber-300/[0.04] p-3"
      >
        <SectionHeading id="analysis-limitations-heading">
          局限与说明
        </SectionHeading>
        {report.limitations.length > 0 ? (
          <ul className="mt-2 grid gap-1 text-[11px] leading-relaxed text-amber-100/80">
            {report.limitations.map((limitation) => (
              <li key={limitation}>· {limitation}</li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-[11px] text-white/45">无额外局限说明。</p>
        )}
      </section>

      {process.env.NODE_ENV !== "production" && (
        <details className="rounded-xl border border-white/8 bg-white/[0.02] p-3">
          <summary className="cursor-pointer text-[11px] text-white/50">
            查看原始数据
          </summary>
          <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words font-mono text-[10px] text-white/50">
            {JSON.stringify(report, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}