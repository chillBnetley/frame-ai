"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { MasterVisionStatus } from "@/features/master-vision/components/status";
import { ApiClientError } from "@/lib/api/client";
import {
  comparePersonalStyleVersions,
  fetchPersonalStyle,
  fetchPersonalStyleVersions,
  restorePersonalStyleVersion,
} from "@/lib/api/personal-style";
import type {
  PersonalStyleCompareResponse,
  PersonalStyleDetailResponse,
  PersonalStyleVersionSummary,
} from "@/types/personal-style";

import { VisualDnaNav } from "./visual-dna-nav";
import {
  CHANGE_SOURCE_LABELS,
  formatChangeValue,
  formatDateTime,
} from "../presentation";

export function VisualDnaVersions({ styleId }: { styleId: string }) {
  const router = useRouter();
  const [detail, setDetail] = useState<PersonalStyleDetailResponse | null>(null);
  const [versions, setVersions] = useState<PersonalStyleVersionSummary[] | null>(null);
  const [fromVersion, setFromVersion] = useState("");
  const [toVersion, setToVersion] = useState("");
  const [compare, setCompare] = useState<PersonalStyleCompareResponse | null>(null);
  const [compareError, setCompareError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busyVersion, setBusyVersion] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      fetchPersonalStyle(styleId, { signal: controller.signal }),
      fetchPersonalStyleVersions(styleId, controller.signal),
    ])
      .then(([nextDetail, nextVersions]) => {
        if (controller.signal.aborted) return;
        setDetail(nextDetail);
        setVersions(nextVersions.versions);
        const latest = nextVersions.versions[0]?.version ?? "";
        const previous = nextVersions.versions[1]?.version ?? latest;
        setFromVersion(previous);
        setToVersion(latest);
        setLoadError(null);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setLoadError(
            reason instanceof ApiClientError
              ? reason.message
              : "无法加载版本历史，请确认 API 服务已经启动。",
          );
        }
      });
    return () => controller.abort();
  }, [attempt, styleId]);

  useEffect(() => {
    if (fromVersion === "" || toVersion === "" || fromVersion === toVersion) {
      return;
    }
    const controller = new AbortController();
    comparePersonalStyleVersions(styleId, fromVersion, toVersion, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) {
          setCompare(result);
          setCompareError(null);
        }
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setCompare(null);
          setCompareError(
            reason instanceof ApiClientError ? reason.message : "版本比较失败。",
          );
        }
      });
    return () => controller.abort();
  }, [fromVersion, styleId, toVersion]);

  async function handleRestore(version: string) {
    if (!window.confirm(`恢复版本 v${version}？系统会以当前最新版本为基础生成一个新版本。`)) {
      return;
    }
    setBusyVersion(version);
    try {
      await restorePersonalStyleVersion(styleId, version);
      router.push(`/visual-dna/${encodeURIComponent(styleId)}`);
    } catch (reason: unknown) {
      setCompareError(
        reason instanceof ApiClientError ? reason.message : "恢复版本失败。",
      );
      setBusyVersion(null);
    }
  }

  if (loadError !== null) {
    return (
      <main className="mx-auto w-full max-w-[1080px] px-4 py-6 sm:px-6 lg:px-8">
        <VisualDnaNav />
        <div className="mt-5">
          <MasterVisionStatus
            tone="error"
            title="版本历史加载失败"
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

  if (detail === null || versions === null) {
    return (
      <main className="mx-auto w-full max-w-[1080px] px-4 py-6 sm:px-6 lg:px-8">
        <VisualDnaNav />
        <div className="mt-6 h-40 animate-pulse rounded-2xl border border-[#e4e8e5] bg-[#f4f7f5]" />
      </main>
    );
  }

  const current = detail.style.version;
  const fields = [
    { key: "profile.name", label: "名称" },
    { key: "profile.description", label: "描述" },
    { key: "profile.color.tendency", label: "色彩倾向" },
    { key: "profile.light.contrast", label: "影调" },
    { key: "profile.light.expression", label: "光线" },
    { key: "profile.texture.grain", label: "颗粒" },
    { key: "profile.sceneFit.suitable", label: "适用场景" },
    { key: "profile.personal.targets", label: "数值偏好" },
    { key: "profile.personal.avoid", label: "避免效果" },
    { key: "profile.personal.confidence", label: "置信度" },
  ];
  const visibleChanges =
    compare?.changes.filter(
      (change) =>
        fields.some((field) => change.path === field.key || change.path.startsWith(`${field.key}.`)) ||
        change.path.startsWith("definition.userOverrides"),
    ) ?? [];

  return (
    <main className="mx-auto w-full max-w-[1080px] px-4 py-6 sm:px-6 lg:px-8">
      <VisualDnaNav />
      <div className="mt-6 flex flex-wrap items-end justify-between gap-4 border-b border-[#e4e8e5] pb-5">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.28em] text-[#8a9a93]">
            VERSION HISTORY
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-[-0.045em] text-[#1d2521]">
            「{detail.style.name}」版本历史
          </h1>
          <p className="mt-2 text-sm text-[#68746e]">
            当前 v{current} · 每次编辑或融合都会形成新版本，旧版本保留。
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
        <h2 className="text-sm font-semibold text-[#202522]">版本列表</h2>
        <ul className="mt-3 divide-y divide-[#eef1ef]">
          {versions.map((version) => (
            <li key={version.version} className="flex flex-wrap items-center justify-between gap-3 py-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-[#2a3530]">v{version.version}</span>
                  {version.version === current && (
                    <span className="rounded-full border border-[#c4ddcf] bg-[#f1f8f4] px-2 py-0.5 text-[9px] text-[#25624f]">
                      当前版本
                    </span>
                  )}
                  <span className="rounded-full border border-[#e4e8e5] bg-[#f7f9f7] px-2 py-0.5 text-[9px] text-[#6b7a73]">
                    {CHANGE_SOURCE_LABELS[version.changeSource]}
                  </span>
                </div>
                <p className="mt-1 text-[11px] text-[#8a9690]">
                  {formatDateTime(version.createdAt)}
                  {version.changeNote ? ` · ${version.changeNote}` : ""}
                </p>
              </div>
              <button
                type="button"
                disabled={version.version === current || busyVersion !== null}
                onClick={() => void handleRestore(version.version)}
                className="inline-flex min-h-9 items-center rounded-lg border border-[#d7dfda] bg-white px-3 text-[11px] font-medium text-[#415049] hover:bg-[#f7faf8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50"
              >
                {busyVersion === version.version ? "恢复中…" : "恢复为新版本"}
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-6 rounded-2xl border border-[#dfe5e1] bg-white p-5">
        <h2 className="text-sm font-semibold text-[#202522]">比较两个版本</h2>
        <div className="mt-3 flex flex-wrap gap-3">
          <label className="text-xs text-[#4a574f]">
            从
            <select
              value={fromVersion}
              onChange={(event) => setFromVersion(event.target.value)}
              className="ml-2 min-h-10 rounded-xl border border-[#dfe5e1] bg-white px-3 text-xs text-[#2a3530] focus:border-[#9dbdaf] focus:outline-none"
            >
              {versions.map((version) => (
                <option key={version.version} value={version.version}>
                  v{version.version}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-[#4a574f]">
            到
            <select
              value={toVersion}
              onChange={(event) => setToVersion(event.target.value)}
              className="ml-2 min-h-10 rounded-xl border border-[#dfe5e1] bg-white px-3 text-xs text-[#2a3530] focus:border-[#9dbdaf] focus:outline-none"
            >
              {versions.map((version) => (
                <option key={version.version} value={version.version}>
                  v{version.version}
                </option>
              ))}
            </select>
          </label>
        </div>

        {compareError !== null && (
          <div role="alert" className="mt-3 rounded-xl border border-[#efc9c4] bg-[#fdf4f2] px-4 py-3 text-xs text-[#8a3a2e]">
            {compareError}
          </div>
        )}

        {fromVersion === toVersion ? (
          <p className="mt-3 text-[11px] text-[#8a9690]">请选择两个不同的版本进行比较。</p>
        ) : compare === null ||
          compare.fromVersion !== fromVersion ||
          compare.toVersion !== toVersion ? (
          <p className="mt-3 text-[11px] text-[#8a9690]">正在比较…</p>
        ) : visibleChanges.length === 0 ? (
          <p className="mt-3 text-[11px] text-[#8a9690]">两个版本在主要字段上没有差异。</p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[520px] border-collapse text-left text-[11px]">
              <thead>
                <tr className="border-b border-[#e4e8e5] text-[10px] uppercase tracking-[0.12em] text-[#8a9a93]">
                  <th className="py-2 pr-3 font-medium">字段</th>
                  <th className="py-2 pr-3 font-medium">v{fromVersion}</th>
                  <th className="py-2 font-medium">v{toVersion}</th>
                </tr>
              </thead>
              <tbody>
                {visibleChanges.map((change) => (
                  <tr key={change.path} className="border-b border-[#f0f3f1] align-top">
                    <td className="py-2 pr-3 font-mono text-[10px] text-[#6b7a73]">
                      {change.path}
                    </td>
                    <td className="py-2 pr-3 text-[#8a9690]">
                      {formatChangeValue(change.before)}
                    </td>
                    <td className="py-2 text-[#2a3530]">
                      {formatChangeValue(change.after)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
