"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { MasterVisionStatus } from "@/features/master-vision/components/status";
import { ApiClientError } from "@/lib/api/client";
import {
  applyPersonalStyleRefinement,
  fetchPersonalStyle,
  refinePersonalStyle,
} from "@/lib/api/personal-style";
import type {
  CustomStyleRefineResponse,
  PersonalStyleDetailResponse,
  PersonalStyleProfile,
  StyleAuthoringDraft,
} from "@/types/personal-style";

import { VisualDnaNav } from "./visual-dna-nav";
import { formatPercent, formatTargetValue, targetLabel } from "../presentation";

const QUICK_INSTRUCTIONS = [
  "更克制一点",
  "保留更多高光",
  "暗部不要太黑",
  "肤色不要偏冷",
  "风格更明显一点",
];

interface ChangeRow {
  label: string;
  before: string;
  after: string;
}

function _list(values: readonly string[]): string {
  return values.length === 0 ? "无" : values.join("、");
}

function collectChanges(
  base: PersonalStyleProfile,
  draft: StyleAuthoringDraft,
): ChangeRow[] {
  const rows: ChangeRow[] = [];
  const push = (label: string, before: string, after: string) => {
    if (before !== after) rows.push({ label, before, after });
  };
  push("名称", base.name, draft.name);
  push("描述", base.description, draft.description);
  push("色彩倾向", base.color.tendency, draft.color.tendency);
  push("色彩关系", base.color.relationships, draft.color.relationships);
  push("饱和度", base.color.saturation, draft.color.saturation);
  push("影调反差", base.light.contrast, draft.light.contrast);
  push("暗部表现", base.light.shadows, draft.light.shadows);
  push("高光表现", base.light.highlights, draft.light.highlights);
  push("光线表达", base.light.expression, draft.light.expression);
  push("颗粒", base.texture.grain, draft.texture.grain);
  push("锐度", base.texture.sharpness, draft.texture.sharpness);
  push("细节", base.texture.detail, draft.texture.detail);
  const keys = new Set([
    ...Object.keys(base.personal.targets ?? {}),
    ...Object.keys(draft.targets ?? {}),
  ]);
  for (const key of Array.from(keys).sort()) {
    const before = base.personal.targets?.[key] ?? 0;
    const after = (draft.targets ?? {})[key] ?? 0;
    if (Math.abs(before - after) >= 0.005) {
      rows.push({
        label: `${targetLabel(key)}目标`,
        before: formatTargetValue(before),
        after: formatTargetValue(after),
      });
    }
  }
  push(
    "适用场景",
    _list(base.sceneFit.suitable),
    _list(draft.suitableScenes),
  );
  push(
    "避免效果",
    _list(base.personal.avoid),
    _list(draft.avoid),
  );
  push(
    "保护约束",
    _list(base.personal.protected),
    _list(draft.protected),
  );
  return rows;
}

export function VisualDnaRefine({ styleId }: { styleId: string }) {
  const router = useRouter();
  const [detail, setDetail] = useState<PersonalStyleDetailResponse | null>(null);
  const [instruction, setInstruction] = useState("");
  const [preview, setPreview] = useState<CustomStyleRefineResponse | null>(null);
  const [parsing, setParsing] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    fetchPersonalStyle(styleId, { signal: controller.signal })
      .then((response) => {
        if (!controller.signal.aborted) {
          setDetail(response);
          setLoadError(null);
        }
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

  async function handleRefine() {
    if (instruction.trim().length === 0 || parsing || applying) return;
    setParsing(true);
    setError(null);
    try {
      const response = await refinePersonalStyle(styleId, instruction.trim());
      setPreview(response);
    } catch (reason: unknown) {
      setError(
        reason instanceof ApiClientError ? reason.message : "无法解析修改指令，请稍后重试。",
      );
    } finally {
      setParsing(false);
    }
  }

  async function handleApply() {
    if (preview === null || applying) return;
    setApplying(true);
    setError(null);
    try {
      await applyPersonalStyleRefinement(styleId, preview.draft, {
        note: instruction.trim() || "自然语言调整",
      });
      router.push(`/visual-dna/${encodeURIComponent(styleId)}`);
    } catch (reason: unknown) {
      setError(
        reason instanceof ApiClientError ? reason.message : "应用修改失败，请稍后重试。",
      );
      setApplying(false);
    }
  }

  if (loadError !== null) {
    return (
      <main className="mx-auto w-full max-w-[1080px] px-4 py-6 sm:px-6 lg:px-8">
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
      <main className="mx-auto w-full max-w-[1080px] px-4 py-6 sm:px-6 lg:px-8">
        <VisualDnaNav />
        <div className="mt-6 h-40 animate-pulse rounded-2xl border border-[#e4e8e5] bg-[#f4f7f5]" />
      </main>
    );
  }

  const changes = preview === null ? [] : collectChanges(detail.style, preview.draft);

  return (
    <main className="mx-auto w-full max-w-[1080px] px-4 py-6 sm:px-6 lg:px-8">
      <VisualDnaNav />
      <div className="mt-6 flex flex-wrap items-end justify-between gap-4 border-b border-[#e4e8e5] pb-5">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.28em] text-[#8a9a93]">
            REFINE VISUAL DNA
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-[-0.045em] text-[#1d2521]">
            继续调整「{detail.style.name}」
          </h1>
          <p className="mt-2 text-sm text-[#68746e]">
            当前 v{detail.style.version}。修改会先生成预览，确认后才写入新版本。
          </p>
        </div>
        <Link
          href={`/visual-dna/${encodeURIComponent(styleId)}`}
          className="text-xs font-medium text-[#277a68] hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          ← 返回工作台
        </Link>
      </div>

      <section className="mt-6 rounded-2xl border border-[#dfe5e1] bg-white p-5">
        <h2 className="text-sm font-semibold text-[#202522]">用自然语言描述修改</h2>
        <div className="mt-3 flex flex-wrap gap-2">
          {QUICK_INSTRUCTIONS.map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => {
                setPreview(null);
                setInstruction((current) =>
                  current.trim().length === 0 ? item : `${current}；${item}`,
                );
              }}
              className="inline-flex min-h-8 items-center rounded-full border border-[#dfe5e1] bg-white px-2.5 text-[10px] text-[#5f6d66] hover:border-[#b9cdc2] hover:bg-[#f7faf8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              {item}
            </button>
          ))}
        </div>
        <textarea
          value={instruction}
          onChange={(event) => {
            setInstruction(event.target.value);
            setPreview(null);
          }}
          maxLength={500}
          rows={4}
          placeholder="例如：更克制一点，保留更多高光，肤色不要偏冷。"
          className="mt-3 w-full rounded-xl border border-[#dfe5e1] px-3.5 py-3 text-sm leading-relaxed text-[#2a3530] placeholder:text-[#a4aea9] focus:border-[#9dbdaf] focus:outline-none"
        />
        <div className="mt-3 flex justify-end">
          <button
            type="button"
            disabled={instruction.trim().length === 0 || parsing || applying}
            onClick={() => void handleRefine()}
            className="inline-flex min-h-10 items-center rounded-xl bg-[#277a68] px-4 text-xs font-medium text-white hover:bg-[#206557] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            {parsing ? "正在解析…" : "解析修改"}
          </button>
        </div>
      </section>

      {error !== null && (
        <div className="mt-4">
          <MasterVisionStatus tone="error" title="操作未完成">
            {error}
          </MasterVisionStatus>
        </div>
      )}

      {preview !== null && (
        <section className="mt-6 space-y-4">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-[#8a9a93]">
                PREVIEW
              </p>
              <h2 className="mt-1 text-xl font-semibold tracking-[-0.03em] text-[#1d2521]">
                修改预览
              </h2>
              <p className="mt-1 text-[11px] text-[#8a9690]">
                {preview.provider.name} / {preview.provider.model} · 置信度{" "}
                {formatPercent(preview.draft.confidence)}
                {preview.provider.isMock ? " · 模拟解析" : ""}
              </p>
            </div>
            <p className="text-[11px] text-[#8a9690]">
              当前 v{preview.currentVersion} · 应用后生成新版本
            </p>
          </div>

          <div className="whitespace-pre-line rounded-xl border border-[#dfe5e1] bg-[#f9fbf9] px-4 py-3 text-xs leading-relaxed text-[#3b4841]">
            {preview.draft.summary}
          </div>

          {changes.length === 0 ? (
            <div className="rounded-xl border border-[#eadfc4] bg-[#fbf7ec] px-4 py-3 text-xs leading-relaxed text-[#7b6228]">
              没有检测到可应用的主要字段变化。可以换一种说法再试。
            </div>
          ) : (
            <div className="overflow-x-auto rounded-xl border border-[#dfe5e1] bg-white">
              <table className="w-full min-w-[560px] border-collapse text-left text-[11px]">
                <thead>
                  <tr className="border-b border-[#e4e8e5] text-[10px] uppercase tracking-[0.12em] text-[#8a9a93]">
                    <th className="px-4 py-2 font-medium">字段</th>
                    <th className="px-4 py-2 font-medium">当前</th>
                    <th className="px-4 py-2 font-medium">调整后</th>
                  </tr>
                </thead>
                <tbody>
                  {changes.map((change) => (
                    <tr key={change.label} className="border-b border-[#f0f3f1] align-top">
                      <td className="px-4 py-2 font-medium text-[#4a574f]">{change.label}</td>
                      <td className="px-4 py-2 text-[#8a9690]">{change.before}</td>
                      <td className="px-4 py-2 text-[#2a3530]">{change.after}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {preview.draft.warnings.length > 0 && (
            <div className="rounded-xl border border-[#efd9b5] bg-[#fdfaf3] p-4">
              <h3 className="text-xs font-semibold text-[#8a6228]">需要确认</h3>
              <ul className="mt-2 list-disc space-y-1 pl-4 text-[11px] leading-relaxed text-[#7b6228]">
                {preview.draft.warnings.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          )}

          {preview.draft.limitations.length > 0 && (
            <div className="rounded-xl border border-[#e4e8e5] bg-[#f7f9f7] p-4">
              <h3 className="text-xs font-semibold text-[#55625b]">限制</h3>
              <ul className="mt-2 list-disc space-y-1 pl-4 text-[11px] leading-relaxed text-[#7a8680]">
                {preview.draft.limitations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#e4e8e5] pt-4">
            <p className="text-[11px] text-[#8a9690]">
              应用后会保存为新版本，旧版本仍然保留；用户已确认字段不会被静默覆盖。
            </p>
            <button
              type="button"
              disabled={applying || changes.length === 0}
              onClick={() => void handleApply()}
              className="inline-flex min-h-11 items-center rounded-xl bg-[#277a68] px-5 text-sm font-medium text-white hover:bg-[#206557] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              {applying ? "正在应用…" : "应用为新版本"}
            </button>
          </div>
        </section>
      )}
    </main>
  );
}
