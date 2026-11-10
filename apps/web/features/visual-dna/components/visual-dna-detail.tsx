"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { MasterVisionStatus } from "@/features/master-vision/components/status";
import { ApiClientError } from "@/lib/api/client";
import {
  analyzePersonalStyle,
  deletePersonalStyle,
  fetchPersonalStyle,
  fetchPersonalStyleAnalysis,
  fetchReferenceFeatures,
  fusePersonalStyle,
  removePersonalStyleReference,
  setPersonalStyleFavorite,
  setPersonalStyleStatus,
} from "@/lib/api/personal-style";
import type {
  PersonalStyleAnalysisResponse,
  PersonalStyleDetailResponse,
  PersonalStyleFusionResponse,
  PersonalStyleReference,
  PersonalStyleReferenceContribution,
  PersonalStyleStatus,
  PhotoVisualFeatures,
} from "@/types/personal-style";

import { AddReferencesSection } from "./add-references-section";
import { FusionResultPanel } from "./fusion-result-panel";
import { ReferenceAnalysisPanel } from "./reference-analysis-panel";
import { TraitPanel } from "./trait-panel";
import { VisualDnaNav } from "./visual-dna-nav";
import {
  SOURCE_LABELS,
  STYLE_STATUS_LABELS,
  formatDateTime,
  formatPercent,
} from "../presentation";

type Action = "analyze" | "fuse" | "favorite" | "status" | "delete" | null;

function actionError(reason: unknown, fallback: string): string {
  return reason instanceof ApiClientError ? reason.message : fallback;
}

const POLL_INTERVAL_MS = 1500;

export function VisualDnaDetail({
  styleId,
  autoStart = false,
}: {
  styleId: string;
  autoStart?: boolean;
}) {
  const router = useRouter();
  const [detail, setDetail] = useState<PersonalStyleDetailResponse | null>(null);
  const [analysis, setAnalysis] = useState<PersonalStyleAnalysisResponse | null>(null);
  const [features, setFeatures] = useState<Record<string, PhotoVisualFeatures>>({});
  const [featuresLoadingId, setFeaturesLoadingId] = useState<string | null>(null);
  const [fusion, setFusion] = useState<PersonalStyleFusionResponse | null>(null);
  const [contributions, setContributions] = useState<
    PersonalStyleReferenceContribution[]
  >([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionFailure, setActionFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState<Action>(null);
  const [attempt, setAttempt] = useState(0);
  const autoStarted = useRef(false);

  const refresh = useCallback(async () => {
    const [nextDetail, nextAnalysis] = await Promise.all([
      fetchPersonalStyle(styleId),
      fetchPersonalStyleAnalysis(styleId),
    ]);
    setDetail(nextDetail);
    setAnalysis(nextAnalysis);
  }, [styleId]);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      fetchPersonalStyle(styleId, { signal: controller.signal }),
      fetchPersonalStyleAnalysis(styleId, controller.signal),
    ])
      .then(([nextDetail, nextAnalysis]) => {
        if (!controller.signal.aborted) {
          setDetail(nextDetail);
          setAnalysis(nextAnalysis);
          setLoadError(null);
        }
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setLoadError(actionError(reason, "无法加载个人风格，请确认 API 服务已经启动。"));
        }
      });
    return () => controller.abort();
  }, [attempt, styleId]);

  const hasRunningAnalysis =
    analysis?.references.some(
      (item) => item.status === "pending" || item.status === "processing",
    ) ?? false;

  useEffect(() => {
    if (!hasRunningAnalysis) return;
    let alive = true;
    const timer = window.setInterval(() => {
      fetchPersonalStyleAnalysis(styleId)
        .then((next) => {
          if (alive) setAnalysis(next);
        })
        .catch((reason: unknown) => {
          if (alive) {
            setActionFailure(actionError(reason, "刷新分析状态失败。"));
          }
        });
    }, POLL_INTERVAL_MS);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [hasRunningAnalysis, styleId]);

  const startAnalysis = useCallback(
    async (force: boolean, referenceIds?: string[]) => {
      setBusy("analyze");
      setActionFailure(null);
      setActionMessage(null);
      try {
        const next = await analyzePersonalStyle(styleId, {
          force,
          referenceIds,
        });
        setAnalysis(next);
        if (force) {
          setFeatures((current) => {
            if (referenceIds === undefined) return {};
            const nextFeatures = { ...current };
            for (const referenceId of referenceIds) {
              delete nextFeatures[referenceId];
            }
            return nextFeatures;
          });
          setFusion(null);
          setContributions([]);
        }
        setActionMessage("分析任务已启动，状态会自动刷新。");
      } catch (reason: unknown) {
        setActionFailure(actionError(reason, "无法启动分析，请稍后重试。"));
      } finally {
        setBusy(null);
      }
    },
    [styleId],
  );

  useEffect(() => {
    if (
      !autoStart ||
      autoStarted.current ||
      detail === null ||
      analysis === null ||
      analysis.references.length === 0 ||
      !analysis.references.every((item) => item.status === "analysis_required")
    ) {
      return;
    }
    autoStarted.current = true;
    void startAnalysis(false);
  }, [analysis, autoStart, detail, startAnalysis]);

  async function handleFuse() {
    setBusy("fuse");
    setActionFailure(null);
    setActionMessage(null);
    try {
      const result = await fusePersonalStyle(styleId);
      setFusion(result);
      setContributions(result.contributions);
      setDetail(await fetchPersonalStyle(styleId));
      setActionMessage(`已生成新版本 v${result.version}。`);
    } catch (reason: unknown) {
      setActionFailure(actionError(reason, "生成个人风格失败，请稍后重试。"));
    } finally {
      setBusy(null);
    }
  }

  async function toggleFavorite() {
    if (detail === null) return;
    const next = !detail.favorite;
    setBusy("favorite");
    setActionFailure(null);
    try {
      await setPersonalStyleFavorite(styleId, next);
      setDetail({ ...detail, favorite: next });
    } catch (reason: unknown) {
      setActionFailure(actionError(reason, "收藏操作失败。"));
    } finally {
      setBusy(null);
    }
  }

  async function changeStatus(status: PersonalStyleStatus) {
    setBusy("status");
    setActionFailure(null);
    setActionMessage(null);
    try {
      await setPersonalStyleStatus(styleId, status);
      setDetail(await fetchPersonalStyle(styleId));
      setActionMessage(
        status === "published" ? "个人风格已发布。" : "个人风格已停用。",
      );
    } catch (reason: unknown) {
      setActionFailure(actionError(reason, "更新状态失败。"));
    } finally {
      setBusy(null);
    }
  }

  async function handleDelete() {
    if (detail === null) return;
    if (
      !window.confirm(
        `确定删除「${detail.style.name}」吗？风格版本、参考照片关联与分析特征会被删除，原始图片会保留。`,
      )
    ) {
      return;
    }
    setBusy("delete");
    setActionFailure(null);
    try {
      await deletePersonalStyle(styleId);
      router.push("/visual-dna");
    } catch (reason: unknown) {
      setActionFailure(actionError(reason, "删除个人风格失败。"));
      setBusy(null);
    }
  }

  async function toggleReferenceFeatures(referenceId: string) {
    if (features[referenceId] !== undefined) {
      setFeatures((current) => {
        const next = { ...current };
        delete next[referenceId];
        return next;
      });
      return;
    }
    setFeaturesLoadingId(referenceId);
    setActionFailure(null);
    try {
      const next = await fetchReferenceFeatures(styleId, referenceId);
      setFeatures((current) => ({ ...current, [referenceId]: next }));
    } catch (reason: unknown) {
      setActionFailure(actionError(reason, "读取照片特征失败。"));
    } finally {
      setFeaturesLoadingId(null);
    }
  }

  async function handleRemoveReference(reference: PersonalStyleReference) {
    if (!window.confirm(`从个人风格中移除「${reference.originalName}」？该照片的提取特征会一并删除。`)) {
      return;
    }
    setActionFailure(null);
    try {
      await removePersonalStyleReference(styleId, reference.id);
      setFusion(null);
      setContributions([]);
      await refresh();
    } catch (reason: unknown) {
      setActionFailure(actionError(reason, "移除参考照片失败。"));
    }
  }

  if (loadError !== null) {
    return (
      <main className="mx-auto w-full max-w-[1280px] px-4 py-6 sm:px-6 lg:px-8">
        <VisualDnaNav />
        <div className="mt-5">
          <MasterVisionStatus
            tone="error"
            title="个人风格加载失败"
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

  if (detail === null) {
    return (
      <main className="mx-auto w-full max-w-[1280px] px-4 py-6 sm:px-6 lg:px-8">
        <VisualDnaNav />
        <div className="mt-6 h-40 animate-pulse rounded-2xl border border-[#e4e8e5] bg-[#f4f7f5]" />
      </main>
    );
  }

  const { style } = detail;
  const running = analysis?.references.some(
    (item) => item.status === "pending" || item.status === "processing",
  );
  const analyzed = (analysis?.completedCount ?? 0) > 0;

  return (
    <main className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8">
      <VisualDnaNav />
      <header className="mt-6 rounded-2xl border border-[#dfe5e1] bg-white p-5 shadow-[0_24px_60px_-50px_rgba(20,45,34,0.5)] sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Link
                href="/visual-dna"
                className="text-[11px] font-medium text-[#277a68] hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                ← 我的风格
              </Link>
              <span className="rounded-full border border-[#dbe5e0] bg-[#f4f8f6] px-2 py-0.5 text-[9px] font-medium text-[#365148]">
                {SOURCE_LABELS[detail.source]}
              </span>
              <span className="rounded-full border border-[#e4e8e5] bg-[#f7f9f7] px-2 py-0.5 text-[9px] font-medium text-[#6b7a73]">
                {STYLE_STATUS_LABELS[detail.status]}
              </span>
              <span className="text-[9px] text-[#8a9690]">
                v{style.version} · 更新于 {formatDateTime(detail.updatedAt)}
              </span>
            </div>
            <h1 className="mt-2 text-3xl font-semibold tracking-[-0.045em] text-[#1d2521]">
              {style.name}
            </h1>
            <p className="mt-2 max-w-3xl whitespace-pre-line text-sm leading-relaxed text-[#66716b]">
              {style.description}
            </p>
            <p className="mt-3 text-[11px] text-[#8a9690]">
              置信度 {formatPercent(style.personal.confidence)} · 样本 {style.personal.sampleCount} 张 ·
              参考照片 {detail.references.length} 张 · 默认强度{" "}
              {formatPercent(style.defaultStrength)}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => void toggleFavorite()}
              aria-pressed={detail.favorite}
              className="inline-flex min-h-10 items-center rounded-xl border border-[#d7dfda] bg-white px-3.5 text-xs font-medium text-[#415049] hover:bg-[#f7faf8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50 aria-pressed:border-[#bfd5ca] aria-pressed:bg-[#f0f7f4] aria-pressed:text-[#277a68]"
            >
              {detail.favorite ? "已收藏" : "收藏"}
            </button>
            <Link
              href={`/visual-dna/${encodeURIComponent(styleId)}/edit`}
              className="inline-flex min-h-10 items-center rounded-xl border border-[#d7dfda] bg-white px-3.5 text-xs font-medium text-[#415049] hover:bg-[#f7faf8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              编辑风格
            </Link>
            <Link
              href={`/visual-dna/${encodeURIComponent(styleId)}/refine`}
              className="inline-flex min-h-10 items-center rounded-xl border border-[#d7dfda] bg-white px-3.5 text-xs font-medium text-[#415049] hover:bg-[#f7faf8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              继续调整
            </Link>
            <Link
              href={`/visual-dna/${encodeURIComponent(styleId)}/evolve`}
              className="inline-flex min-h-10 items-center rounded-xl border border-[#d7dfda] bg-white px-3.5 text-xs font-medium text-[#415049] hover:bg-[#f7faf8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              反馈演变
            </Link>
            <Link
              href={`/visual-dna/${encodeURIComponent(styleId)}/versions`}
              className="inline-flex min-h-10 items-center rounded-xl border border-[#d7dfda] bg-white px-3.5 text-xs font-medium text-[#415049] hover:bg-[#f7faf8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              版本历史
            </Link>
            {detail.status === "published" ? (
              <button
                type="button"
                disabled={busy !== null}
                onClick={() => void changeStatus("disabled")}
                className="inline-flex min-h-10 items-center rounded-xl border border-[#d7dfda] bg-white px-3.5 text-xs font-medium text-[#8a6228] hover:bg-[#fdfaf3] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50"
              >
                停用
              </button>
            ) : (
              <button
                type="button"
                disabled={busy !== null}
                onClick={() => void changeStatus("published")}
                className="inline-flex min-h-10 items-center rounded-xl bg-[#277a68] px-4 text-xs font-medium text-white hover:bg-[#206557] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50"
              >
                发布
              </button>
            )}
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => void handleDelete()}
              className="inline-flex min-h-10 items-center rounded-xl px-3 text-xs font-medium text-[#8a3a2e] hover:bg-[#fdf4f2] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50"
            >
              删除
            </button>
          </div>
        </div>
      </header>

      {actionFailure !== null && (
        <div className="mt-4">
          <MasterVisionStatus tone="error" title="操作未完成">
            {actionFailure}
          </MasterVisionStatus>
        </div>
      )}
      {actionMessage !== null && (
        <div className="mt-4">
          <MasterVisionStatus tone="success" title="操作完成">
            {actionMessage}
          </MasterVisionStatus>
        </div>
      )}

      <div className="mt-6 grid gap-6 xl:grid-cols-[1.08fr_0.92fr] xl:items-start">
        <div className="space-y-6">
          <ReferenceAnalysisPanel
            references={detail.references}
            analysis={analysis}
            features={features}
            featuresLoadingId={featuresLoadingId}
            contributions={contributions}
            busy={busy === "analyze" || busy === "fuse" ? busy : null}
            error={null}
            onToggleFeatures={(referenceId) => void toggleReferenceFeatures(referenceId)}
            onRemoveReference={(reference) => void handleRemoveReference(reference)}
            onAnalyze={() => void startAnalysis(analyzed || running === true)}
            onAnalyzeReference={(referenceId) =>
              void startAnalysis(true, [referenceId])
            }
            onFuse={() => void handleFuse()}
          />
          <AddReferencesSection
            styleId={styleId}
            references={detail.references}
            onAdded={() => {
              setFusion(null);
              setContributions([]);
              void refresh();
            }}
          />
          {fusion !== null && <FusionResultPanel fusion={fusion} />}
        </div>
        <aside className="space-y-4">
          <div className="rounded-2xl border border-[#dfe5e1] bg-white p-5">
            <TraitPanel profile={style} />
          </div>
          <div className="rounded-xl border border-[#dfe5e1] bg-[#f9fbf9] p-4 text-[11px] leading-relaxed text-[#7a8680]">
            <p className="font-semibold text-[#55625b]">隐私与授权</p>
            <p className="mt-1">
              参考照片仅在你主动授权后用于本风格分析，不用于模型训练，也不会自动公开。
              移除参考照片会同时删除该照片的提取特征，但不会删除你的原始图片或已发布风格版本。
            </p>
          </div>
        </aside>
      </div>
    </main>
  );
}
