"use client";

import { useId, useState } from "react";

import type { UseAnalysisResult } from "@/features/analysis/hooks/use-analysis";
import {
  categoryLabel,
  describeAnalysisStage,
  issueTypeLabel,
  sceneLabel,
  SEVERITY_LABELS,
} from "@/features/analysis/presentation";
import { isChatPatch } from "@/features/editor/state/editor-reducer";
import type {
  EditorProposal,
  ProposalPatch,
  ProposalView,
} from "@/features/editor/state/editor-reducer";
import type { UsePhotographerChatResult } from "@/features/photographer/hooks/use-photographer-chat";
import type {
  UsePhotographerCritiqueResult,
} from "@/features/photographer/hooks/use-photographer-critique";
import { isActionableSuggestion } from "@/features/photographer/hooks/use-photographer-critique";
import type { UseFeedbackResult } from "@/features/photographer/hooks/use-feedback";
import type { UseStylesResult } from "@/features/photographer/hooks/use-styles";
import {
  changeLabel,
  findStyle,
  groupStylesByScene,
  PARAMETERIZED_STYLE_NOTE,
  STYLE_CATEGORY_LABELS,
  ZERO_STRENGTH_NOTE,
} from "@/features/photographer/presentation";
import { FeedbackSection } from "@/features/photographer/components/feedback-section";
import { ERROR_FALLBACK_MESSAGE } from "@/lib/error-messages";
import type {
  PhotographerCritiquePoint,
  PhotographerDiagnosisItem,
  PhotographerParameterChange,
  PhotographerStyle,
  SceneLabel,
} from "@/types/photographer";

const primaryButton =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-accent px-4 text-xs font-semibold text-[#101208] transition-colors hover:bg-accent/85 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-40";
const secondaryButton =
  "inline-flex min-h-11 items-center gap-2 rounded-lg border border-white/12 bg-white/[0.03] px-3 text-xs text-white/65 transition-colors hover:bg-white/[0.07] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-40";
const toggleButton =
  "inline-flex min-h-9 items-center rounded-lg border border-white/12 bg-white/[0.03] px-2.5 text-[11px] text-white/60 transition-colors hover:bg-white/[0.07] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent aria-pressed:border-accent/40 aria-pressed:bg-accent/10 aria-pressed:text-accent";

const styleChip =
  "inline-flex min-h-9 items-center rounded-lg border border-white/12 bg-white/[0.03] px-2.5 text-[11px] text-white/60 transition-colors hover:bg-white/[0.07] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent aria-pressed:border-accent/40 aria-pressed:bg-accent/10 aria-pressed:text-accent disabled:cursor-not-allowed disabled:opacity-40";

export interface PhotographerPanelProps {
  open: boolean;
  onClose: () => void;
  imageId: string;
  analysis: UseAnalysisResult;
  proposal: EditorProposal;
  canAccept: boolean;
  dirty: boolean;
  styles: UseStylesResult;
  chat: UsePhotographerChatResult;
  critique: UsePhotographerCritiqueResult;
  selectedStyleId: string | null;
  styleStrength: number;
  feedback: UseFeedbackResult;
  onStart: () => void;
  onRetry: () => void;
  onCancel: () => void;
  onView: (view: ProposalView) => void;
  onAccept: () => void;
  onAbandon: () => void;
  onSelectStyle: (style: PhotographerStyle | null) => void;
  onStyleStrengthChange: (value: number) => void;
  onStyleStrengthCommit: () => void;
  className?: string;
}

function formatChangeValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "—";
  }
  if (Array.isArray(value)) {
    return `${value.length} 个点`;
  }
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  }
  if (typeof value === "object") {
    return "结构已更新";
  }
  return String(value);
}

function DiagnosisSection({
  title,
  items,
}: {
  title: string;
  items: readonly PhotographerDiagnosisItem[];
}) {
  if (items.length === 0) {
    return null;
  }
  return (
    <section aria-label={title} className="grid gap-2">
      <h4 className="text-[11px] font-medium text-white/70">{title}</h4>
      <ul className="grid gap-1.5">
        {items.map((item) => (
          <li
            key={item.issueId}
            className="rounded-lg border border-white/8 bg-white/[0.02] px-3 py-2"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-[11px] text-white/75">
                {issueTypeLabel(item.type)}
              </span>
              <span className="rounded-full border border-white/10 px-2 py-0.5 font-mono text-[10px] text-white/45">
                严重度 {SEVERITY_LABELS[item.severity]}
              </span>
            </div>
            <p className="mt-1 text-[11px] leading-relaxed text-white/50">
              {item.evidence}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}

function ChangeList({
  changes,
}: {
  changes: readonly PhotographerParameterChange[];
}) {
  if (changes.length === 0) {
    return (
      <p className="rounded-lg border border-white/8 bg-white/[0.02] px-3 py-2 text-[11px] text-white/55">
        当前照片无需主要调整
      </p>
    );
  }
  return (
    <ul className="grid gap-1.5">
      {changes.map((change) => (
        <li
          key={change.path}
          className="rounded-lg border border-white/8 bg-white/[0.02] px-3 py-2"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-[11px] text-white/75">
              {changeLabel(change.path)}
            </span>
            <span className="font-mono text-[10px] text-white/45">
              {formatChangeValue(change.previous)} →{" "}
              {formatChangeValue(change.proposed)}
            </span>
          </div>
          <p className="mt-1 text-[11px] leading-relaxed text-white/45">
            {change.reason}
          </p>
        </li>
      ))}
    </ul>
  );
}

interface StyleSectionProps {
  styles: UseStylesResult;
  scene: SceneLabel | null;
  selectedStyleId: string | null;
  strength: number;
  busy: boolean;
  onSelect: (style: PhotographerStyle | null) => void;
  onStrengthChange: (value: number) => void;
  onStrengthCommit: () => void;
}

function StyleSection({
  styles,
  scene,
  selectedStyleId,
  strength,
  busy,
  onSelect,
  onStrengthChange,
  onStrengthCommit,
}: StyleSectionProps) {
  const sliderId = useId();
  const selected = findStyle(styles.styles, selectedStyleId);
  const groups = groupStylesByScene(styles.styles, scene);
  const disabled = styles.loading || busy;
  const percent = Math.round(strength * 100);

  return (
    <section
      aria-label="摄影风格"
      className="grid gap-2 rounded-xl border border-white/8 bg-white/[0.02] p-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-[11px] font-medium text-white/70">摄影风格</h4>
        <span className="rounded-full border border-white/10 px-2 py-0.5 font-mono text-[10px] text-white/45">
          {selected === null
            ? "自动优化"
            : `${selected.name} v${selected.version} · 强度 ${percent}%`}
        </span>
      </div>

      {styles.loading && (
        <p className="text-[11px] text-white/45">风格库加载中…</p>
      )}
      {styles.error !== null && !styles.loading && (
        <div className="grid gap-2">
          <p className="text-[11px] text-red-200">
            {styles.error.message || ERROR_FALLBACK_MESSAGE}
          </p>
          <button
            type="button"
            onClick={styles.reload}
            className={secondaryButton}
          >
            重新加载风格库
          </button>
        </div>
      )}

      {!styles.loading && styles.styles.length > 0 && (
        <>
          <div className="grid gap-1.5">
            <button
              type="button"
              aria-pressed={selectedStyleId === null}
              disabled={disabled}
              onClick={() => onSelect(null)}
              className={styleChip}
            >
              自动优化（不选风格）
            </button>
          </div>

          {groups.recommended.length > 0 && (
            <div className="grid gap-1.5">
              <h5 className="text-[10px] text-white/40">
                场景推荐 · {scene === null ? "当前照片" : sceneLabel(scene)}
              </h5>
              <div className="flex flex-wrap gap-1.5">
                {groups.recommended.map((style) => (
                  <button
                    key={style.id}
                    type="button"
                    aria-pressed={style.id === selectedStyleId}
                    disabled={disabled}
                    title={STYLE_CATEGORY_LABELS[style.category]}
                    onClick={() => onSelect(style)}
                    className={styleChip}
                  >
                    {style.name}
                  </button>
                ))}
              </div>
            </div>
          )}

          {groups.others.length > 0 && (
            <div className="grid gap-1.5">
              <h5 className="text-[10px] text-white/40">其他风格</h5>
              <div className="flex flex-wrap gap-1.5">
                {groups.others.map((style) => (
                  <button
                    key={style.id}
                    type="button"
                    aria-pressed={style.id === selectedStyleId}
                    disabled={disabled}
                    title={STYLE_CATEGORY_LABELS[style.category]}
                    onClick={() => onSelect(style)}
                    className={styleChip}
                  >
                    {style.name}
                  </button>
                ))}
              </div>
            </div>
          )}

          {selected !== null && (
            <div className="grid gap-2 border-t border-white/8 pt-2">
              <p className="text-[11px] leading-relaxed text-white/55">
                {selected.description}
              </p>
              <div className="flex items-center justify-between gap-2">
                <label htmlFor={sliderId} className="text-[11px] text-white/65">
                  风格强度
                </label>
                <span className="font-mono text-[10px] text-white/45">
                  {percent}%
                </span>
              </div>
              <input
                id={sliderId}
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={strength}
                disabled={disabled}
                aria-label="风格强度"
                aria-valuetext={`${percent}%`}
                onChange={(event) =>
                  onStrengthChange(Number(event.target.value))
                }
                onPointerUp={onStrengthCommit}
                onKeyUp={onStrengthCommit}
                onBlur={onStrengthCommit}
                className="h-9 w-full cursor-pointer accent-[#d8ff5f] disabled:cursor-not-allowed disabled:opacity-40"
              />
              <p className="text-[10px] leading-relaxed text-white/35">
                {PARAMETERIZED_STYLE_NOTE}
              </p>
              {strength === 0 && (
                <p className="text-[10px] leading-relaxed text-white/35">
                  {ZERO_STRENGTH_NOTE}
                </p>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}

function NoteSection({
  title,
  label = title,
  items,
}: {
  title: string;
  label?: string;
  items: readonly string[];
}) {
  if (items.length === 0) {
    return null;
  }
  return (
    <section aria-label={label} className="grid gap-1">
      <h4 className="text-[11px] font-medium text-white/70">{title}</h4>
      <ul className="grid gap-1 text-[11px] text-white/45">
        {items.map((item) => (
          <li key={item}>· {item}</li>
        ))}
      </ul>
    </section>
  );
}

interface ReviewActionsProps {
  proposal: EditorProposal;
  canAccept: boolean;
  dirty: boolean;
  changes: readonly PhotographerParameterChange[];
  noChangesNote: string;
  onView: (view: ProposalView) => void;
  onAccept: () => void;
  onAbandon: () => void;
}

function ReviewActions({
  proposal,
  canAccept,
  dirty,
  changes,
  noChangesNote,
  onView,
  onAccept,
  onAbandon,
}: ReviewActionsProps) {
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          aria-pressed={proposal.view === "ai"}
          onClick={() => onView("ai")}
          className={toggleButton}
        >
          AI 方案预览
        </button>
        <button
          type="button"
          aria-pressed={proposal.view === "original"}
          onClick={() => onView("original")}
          className={toggleButton}
        >
          原图
        </button>
        <button
          type="button"
          aria-pressed={proposal.view === "editor"}
          onClick={() => onView("editor")}
          className={toggleButton}
        >
          继续调整
        </button>
      </div>

      {changes.length === 0 && (
        <p className="rounded-lg border border-white/8 bg-white/[0.02] px-3 py-2 text-[11px] text-white/55">
          {noChangesNote}
        </p>
      )}
      {dirty && (
        <p className="rounded-lg border border-amber-300/20 bg-amber-300/[0.06] px-3 py-2 text-[11px] text-amber-100">
          有未保存的调整，请先保存或放弃后再接受 AI 方案。
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onAccept}
          disabled={!canAccept || dirty || proposal.accepting}
          className={primaryButton}
        >
          {proposal.accepting ? "正在接受…" : "接受方案"}
        </button>
        <button type="button" onClick={onAbandon} className={secondaryButton}>
          放弃
        </button>
      </div>
    </>
  );
}

function PatchCard({
  patch,
  fromCritique,
}: {
  patch: ProposalPatch;
  fromCritique: boolean;
}) {
  // Only a chat reply can refuse an instruction; a critique patch is always a preview.
  const refused = isChatPatch(patch) && patch.supported === false;
  return (
    <>
      <section
        aria-label={fromCritique ? "点评调整" : "对话调整"}
        className="rounded-xl border border-white/8 bg-white/[0.02] p-3"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 className="text-xs font-medium text-white/80">
            {refused
              ? "这项调整不支持"
              : fromCritique
                ? "点评建议预览"
                : "对话调整建议"}
          </h4>
          <span className="rounded-full border border-white/10 px-2 py-0.5 font-mono text-[10px] text-white/45">
            {refused
              ? "配方未变化"
              : `${patch.changes.length} 项参数变化`}
          </span>
        </div>
        <p className="mt-1 text-[11px] leading-relaxed text-white/50">
          {patch.reason}
        </p>
      </section>

      {refused && (
        <div
          role="alert"
          className="rounded-lg border border-amber-300/25 bg-amber-300/[0.08] px-3 py-2 text-[11px] text-amber-100"
        >
          <p>当前配方未发生变化，画面保持你已有的调整。</p>
          <ul className="mt-1 grid gap-1">
            {patch.unsupported.map((item) => (
              <li key={item}>· 不支持：{item}</li>
            ))}
          </ul>
        </div>
      )}

      <section aria-label="参数变化" className="grid gap-2">
        <h4 className="text-[11px] font-medium text-white/70">参数变化</h4>
        <ChangeList changes={patch.changes} />
      </section>

      <NoteSection title="提示" items={patch.warnings} />
      <NoteSection title="能力限制" items={patch.limitations} />
    </>
  );
}

function EvidenceRefs({ refs }: { refs: readonly string[] }) {
  return (
    <details className="mt-1">
      <summary className="cursor-pointer text-[10px] text-white/35 transition-colors hover:text-white/60">
        证据 {refs.length} 项
      </summary>
      <ul className="mt-1 flex flex-wrap gap-1">
        {refs.map((ref) => (
          <li
            key={ref}
            className="rounded border border-white/10 px-1.5 py-0.5 font-mono text-[10px] text-white/45"
          >
            {ref}
          </li>
        ))}
      </ul>
    </details>
  );
}

function CritiquePoints({
  title,
  items,
  subjective = false,
}: {
  title: string;
  items: readonly PhotographerCritiquePoint[];
  subjective?: boolean;
}) {
  if (items.length === 0) {
    return null;
  }
  return (
    <section aria-label={title} className="grid gap-1.5">
      <h4 className="text-[11px] font-medium text-white/70">{title}</h4>
      <ul className="grid gap-1.5">
        {items.map((point) => (
          <li
            key={point.text}
            className="rounded-lg border border-white/8 bg-white/[0.02] px-3 py-2"
          >
            <p className="flex flex-wrap items-start gap-2 text-[11px] leading-relaxed text-white/65">
              {subjective && (
                <span className="mt-0.5 rounded-full border border-white/12 px-1.5 py-0.5 text-[9px] text-white/45">
                  主观
                </span>
              )}
              <span>{point.text}</span>
            </p>
            <EvidenceRefs refs={point.evidenceRefs} />
          </li>
        ))}
      </ul>
    </section>
  );
}

interface CritiqueSectionProps {
  critique: UsePhotographerCritiqueResult;
  busy: boolean;
}

function CritiqueSection({ critique, busy }: CritiqueSectionProps) {
  const body = critique.critique;
  const alert =
    critique.error === null ? null : (
      <div
        role="alert"
        className="rounded-lg border border-red-300/25 bg-red-300/[0.06] px-3 py-2 text-[11px] text-red-200"
      >
        <p>{critique.error.message || ERROR_FALLBACK_MESSAGE}</p>
        {critique.error.code && (
          <p className="mt-1 font-mono text-[10px] text-red-200/70">
            {critique.error.code}
          </p>
        )}
      </div>
    );

  return (
    <section
      aria-label="AI 摄影点评"
      className="grid gap-2 rounded-xl border border-white/8 bg-white/[0.02] p-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-[11px] font-medium text-white/70">摄影点评</h4>
        <span className="rounded-full border border-white/10 px-2 py-0.5 font-mono text-[10px] text-white/45">
          规则生成
        </span>
      </div>
      <p className="text-[10px] leading-relaxed text-white/40">
        每条结论都引用分析报告里的字段或区域编号，可展开核对；点评不会描述报告里没有的物体。
      </p>

      {body === null ? (
        <>
          {alert}
          <button
            type="button"
            onClick={() => void critique.request()}
            disabled={busy || !critique.canRequest}
            className={secondaryButton}
          >
            {critique.pending ? "正在生成点评…" : "生成摄影点评"}
          </button>
          {!critique.canRequest && !critique.pending && (
            <p className="text-[10px] leading-relaxed text-white/35">
              需要先完成这张照片的 AI 摄影分析，点评才有依据。
            </p>
          )}
        </>
      ) : (
        <>
          {body.isMock && (
            <p className="rounded-lg border border-amber-300/25 bg-amber-300/10 px-3 py-2 text-[11px] text-amber-100">
              本次点评基于模拟分析结果（未调用真实视觉模型）
            </p>
          )}
          {critique.pending && (
            <p className="text-[11px] text-white/55">正在重新生成点评…</p>
          )}
          <CritiquePoints title="优点" items={body.strengths} />
          <CritiquePoints title="技术观测" items={body.technical?.objective ?? []} />
          <CritiquePoints
            title="可能的问题"
            items={body.technical?.possibleIssues ?? []}
          />
          <CritiquePoints title="创作解读" items={body.creative} subjective />

          {body.suggestions.length > 0 && (
            <section aria-label="后期建议" className="grid gap-1.5">
              <h4 className="text-[11px] font-medium text-white/70">
                后期建议
              </h4>
              <ul className="grid gap-1.5">
                {body.suggestions.map((item) => (
                  <li
                    key={item.text}
                    className="rounded-lg border border-white/8 bg-white/[0.02] px-3 py-2"
                  >
                    <p className="flex flex-wrap items-start gap-2 text-[11px] leading-relaxed text-white/65">
                      <span className="mt-0.5 rounded-full border border-white/12 px-1.5 py-0.5 text-[9px] text-white/45">
                        {categoryLabel(item.category)}
                      </span>
                      <span>{item.text}</span>
                    </p>
                    <EvidenceRefs refs={item.evidenceRefs} />
                    {isActionableSuggestion(item) ? (
                      <button
                        type="button"
                        onClick={() => void critique.apply(item)}
                        disabled={busy || !critique.canApply}
                        className={`${toggleButton} mt-1.5`}
                      >
                        {critique.applying ? "正在生成预览…" : "应用到编辑"}
                      </button>
                    ) : (
                      <p className="mt-1.5 text-[10px] text-white/35">
                        这条建议不涉及可调参数，需要通过裁切或拍摄时机实现。
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <NoteSection label="点评局限" title="点评局限" items={body.limitations} />

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void critique.request()}
              disabled={busy || critique.pending}
              className={secondaryButton}
            >
              重新生成点评
            </button>
            <button type="button" onClick={critique.clear} className={secondaryButton}>
              收起点评
            </button>
          </div>
          {alert}
        </>
      )}
    </section>
  );
}

const QUICK_PROMPTS = [
  "降低饱和度",
  "让人物更突出",
  "电影感一点",
  "保留肤色的同时更暖",
  "删除背景里的人物",
];

interface ChatSectionProps {
  chat: UsePhotographerChatResult;
  busy: boolean;
}

function ChatSection({ chat, busy }: ChatSectionProps) {
  const inputId = useId();
  const [draft, setDraft] = useState("");
  const disabled = busy || !chat.canSend;

  const submit = (instruction: string) => {
    const text = instruction.trim();
    if (text === "" || disabled) {
      return;
    }
    void chat.send(text);
    setDraft("");
  };

  return (
    <section
      aria-label="自然语言调整"
      className="grid gap-2 rounded-xl border border-white/8 bg-white/[0.02] p-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-[11px] font-medium text-white/70">对话调整</h4>
        <span className="rounded-full border border-white/10 px-2 py-0.5 font-mono text-[10px] text-white/45">
          最小参数补丁
        </span>
      </div>
      <p className="text-[10px] leading-relaxed text-white/40">
        只移动指令提到的参数；你的曲线、HSL、色彩分级、蒙版与裁剪不会被覆盖。
      </p>

      {chat.turns.length > 0 && (
        <ul aria-label="对话记录" className="grid gap-1.5">
          {chat.turns.map((turn) => (
            <li
              key={turn.id}
              className="rounded-lg border border-white/8 bg-white/[0.02] px-3 py-2"
            >
              <p className="text-[11px] text-white/75">{turn.instruction}</p>
              <p className="mt-1 text-[11px] leading-relaxed text-white/45">
                {turn.pending
                  ? "正在生成补丁…"
                  : turn.failed
                    ? (chat.error?.message ?? "这次调整未完成，配方未变化。")
                    : (turn.reply ?? "已完成调整。")}
              </p>
            </li>
          ))}
        </ul>
      )}

      <label htmlFor={inputId} className="text-[11px] text-white/65">
        用一句话描述你想要的调整
      </label>
      <textarea
        id={inputId}
        rows={2}
        maxLength={500}
        value={draft}
        disabled={disabled}
        aria-label="调整指令"
        placeholder="例如：降低饱和度"
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit(draft);
          }
        }}
        className="min-h-16 rounded-lg border border-white/12 bg-black/30 px-3 py-2 text-[11px] text-white/80 placeholder:text-white/25 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-40"
      />

      <div
        role="group"
        aria-label="快捷指令"
        className="flex flex-wrap gap-1.5"
      >
        {QUICK_PROMPTS.map((prompt) => (
          <button
            key={prompt}
            type="button"
            disabled={disabled}
            onClick={() => submit(prompt)}
            className={toggleButton}
          >
            {prompt}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => submit(draft)}
          disabled={disabled || draft.trim() === ""}
          className={primaryButton}
        >
          {chat.pending ? "正在调整…" : "应用这条指令"}
        </button>
        {chat.turns.length > 0 && (
          <button
            type="button"
            onClick={chat.reset}
            className={secondaryButton}
          >
            清空对话
          </button>
        )}
      </div>

      {!chat.canSend && !chat.pending && (
        <p className="text-[10px] leading-relaxed text-white/35">
          需要当前会话与这张照片的分析结果才能对话调整；先运行分析或生成方案。
        </p>
      )}
    </section>
  );
}

export function PhotographerPanel({
  open,
  onClose,
  imageId,
  analysis,
  proposal,
  canAccept,
  dirty,
  styles,
  chat,
  critique,
  selectedStyleId,
  styleStrength,
  feedback,
  onStart,
  onRetry,
  onCancel,
  onView,
  onAccept,
  onAbandon,
  onSelectStyle,
  onStyleStrengthChange,
  onStyleStrengthCommit,
  className,
}: PhotographerPanelProps) {
  if (!open) {
    return null;
  }

  const plan = proposal.plan;
  const patch = proposal.patch;
  const changes = plan?.changes ?? patch?.changes ?? [];
  const reportMatches =
    analysis.report !== null && analysis.report.image.id === imageId;
  const scene =
    reportMatches && analysis.report !== null
      ? analysis.report.scene.primary
      : null;
  const running = analysis.running;
  const loading = proposal.status === "loading";
  const failed = proposal.status === "error";
  const ready =
    proposal.status === "ready" && (plan !== null || patch !== null);
  const analysisError = analysis.error?.message ?? null;

  return (
    <section
      id="photographer-panel"
      aria-labelledby="photographer-panel-title"
      className={`analysis-panel min-w-0 rounded-2xl border border-white/8 bg-black/20 xl:sticky xl:top-[calc(var(--app-header-height)+1rem)] xl:max-h-[calc(100dvh-var(--app-header-height)-2rem)] xl:overflow-y-auto xl:overscroll-contain ${className ?? ""}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-white/8 px-4 py-3">
        <div>
          <h3
            id="photographer-panel-title"
            className="text-sm font-medium text-white"
          >
            AI 摄影师
          </h3>
          <p className="mt-0.5 text-[11px] text-white/40">
            根据分析结果生成可审查的参数方案，不会直接修改像素。
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="关闭 AI 摄影师"
          className="grid size-11 place-items-center rounded-lg text-white/45 transition-colors hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          <span aria-hidden="true">✕</span>
        </button>
      </div>

      <div className="grid gap-3 p-4">
        {plan?.isMock === true && (
          <p className="rounded-lg border border-amber-300/25 bg-amber-300/10 px-3 py-2 text-[11px] text-amber-100">
            模拟方案（未调用真实 Planner 模型）
          </p>
        )}
        {plan?.degraded === true && (
          <p className="rounded-lg border border-amber-300/25 bg-amber-300/10 px-3 py-2 text-[11px] text-amber-100">
            确定性回退方案（模型输出未通过校验）
          </p>
        )}

        <p
          role="status"
          aria-live="polite"
          className="inline-flex items-center gap-2 text-[11px] text-white/55"
        >
          <span
            aria-hidden="true"
            className={`size-1.5 rounded-full ${
              loading || running
                ? "animate-pulse bg-accent"
                : failed
                  ? "bg-red-400"
                  : ready
                    ? "bg-emerald-400"
                    : "bg-white/30"
            }`}
          />
          {loading
            ? "正在生成方案"
            : running
              ? describeAnalysisStage(analysis.status, analysis.stage)
              : ready
                ? "方案已就绪"
                : failed
                  ? "方案生成失败"
                  : reportMatches
                    ? "已有分析结果，可生成方案"
                    : "尚未分析这张照片"}
        </p>

        {analysisError !== null && !ready && (
          <div
            role="alert"
            className="rounded-lg border border-red-300/25 bg-red-300/[0.06] px-3 py-2 text-[11px] text-red-200"
          >
            <p>{analysisError}</p>
            {analysis.error?.code && (
              <p className="mt-1 font-mono text-[10px] text-red-200/70">
                {analysis.error.code}
              </p>
            )}
          </div>
        )}

        {proposal.error !== null && (
          <div
            role="alert"
            className="rounded-lg border border-red-300/25 bg-red-300/[0.06] px-3 py-2 text-[11px] text-red-200"
          >
            <p>{proposal.error.message || ERROR_FALLBACK_MESSAGE}</p>
            <p className="mt-1 font-mono text-[10px] text-red-200/70">
              {proposal.error.code}
              {proposal.error.requestId
                ? ` · 请求 ID ${proposal.error.requestId}`
                : ""}
            </p>
          </div>
        )}

        <StyleSection
          styles={styles}
          scene={scene}
          selectedStyleId={selectedStyleId}
          strength={styleStrength}
          busy={loading || proposal.accepting}
          onSelect={onSelectStyle}
          onStrengthChange={onStyleStrengthChange}
          onStrengthCommit={onStyleStrengthCommit}
        />

        <ChatSection chat={chat} busy={loading || proposal.accepting} />

        <CritiqueSection
          critique={critique}
          busy={loading || proposal.accepting}
        />

        {!ready && !loading && (
          <div className="grid gap-2 rounded-xl border border-white/8 bg-white/[0.02] p-3">
            <p className="text-[11px] leading-relaxed text-white/55">
              {reportMatches
                ? "将根据已有分析生成参数方案，并在预览区显示“原图 / AI 方案”对比；方案不会自动保存。"
                : "尚未完成分析。点击后先运行 AI 摄影分析，完成后自动生成参数方案。"}
            </p>
            <button
              type="button"
              onClick={failed || analysis.error ? onRetry : onStart}
              disabled={running}
              className={`${primaryButton} w-full`}
            >
              {failed || analysis.error
                ? "重新生成方案"
                : running
                  ? "分析中，完成后自动生成方案"
                  : selectedStyleId === null
                    ? "开始自动优化"
                    : "生成风格方案"}
            </button>
            {running && (
              <button
                type="button"
                onClick={onCancel}
                className={secondaryButton}
              >
                取消
              </button>
            )}
          </div>
        )}

        {loading && (
          <div className="grid gap-2 rounded-xl border border-white/8 bg-white/[0.02] p-3">
            <p className="text-[11px] leading-relaxed text-white/55">
              正在调用 Planner
              并校验参数，通常需要几秒到几十秒。不会写入会话历史。
            </p>
            <button
              type="button"
              onClick={onCancel}
              className={secondaryButton}
            >
              取消生成
            </button>
          </div>
        )}

        {ready && patch !== null && (
          <PatchCard patch={patch} fromCritique={proposal.source === "critique"} />
        )}

        {ready && plan !== null && (
          <>
            <section
              aria-label="创作方向"
              className="rounded-xl border border-white/8 bg-white/[0.02] p-3"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h4 className="text-xs font-medium text-white/80">
                  {plan.direction.name}
                </h4>
                <span className="rounded-full border border-white/10 px-2 py-0.5 font-mono text-[10px] text-white/45">
                  {STYLE_CATEGORY_LABELS[plan.direction.category] ??
                    plan.direction.category}
                </span>
              </div>
              <p className="mt-1 text-[11px] leading-relaxed text-white/50">
                {plan.direction.description}
              </p>
              {plan.styleId !== null && (
                <p className="mt-1 font-mono text-[10px] text-white/40">
                  风格 {plan.styleId} v{plan.styleVersion ?? "1.0"} · 强度{" "}
                  {Math.round((plan.styleStrength ?? 0) * 100)}%（参数化实现，非
                  LUT）
                </p>
              )}
              <p className="mt-2 font-mono text-[10px] text-white/35">
                强度 {Math.round(plan.direction.strength * 100)}% · 置信度{" "}
                {Math.round(plan.confidence * 100)}%（{plan.confidenceNote}）
              </p>
            </section>

            <DiagnosisSection
              title="已确认问题"
              items={plan.diagnosis.confirmed}
            />
            <DiagnosisSection
              title="可能问题"
              items={plan.diagnosis.possible}
            />

            {plan.diagnosis.creativeChoices.length > 0 && (
              <section aria-label="创作选择" className="grid gap-2">
                <h4 className="text-[11px] font-medium text-white/70">
                  创作选择
                </h4>
                <ul className="grid gap-1.5">
                  {plan.diagnosis.creativeChoices.map((choice) => (
                    <li
                      key={`${choice.type}-${choice.description}`}
                      className="rounded-lg border border-white/8 bg-white/[0.02] px-3 py-2 text-[11px] text-white/50"
                    >
                      {choice.description}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <section aria-label="参数变化" className="grid gap-2">
              <h4 className="text-[11px] font-medium text-white/70">
                参数变化
              </h4>
              <ChangeList changes={plan.changes} />
            </section>

            <p className="rounded-lg border border-white/8 bg-white/[0.02] px-3 py-2 text-[11px] text-white/45">
              {plan.recipe.localAdjustments.length > 0
                ? `方案引用了 ${plan.recipe.localAdjustments.length} 个已有或新建的局部掩膜，可在参数面板继续修改。`
                : "本方案未使用局部蒙版；自动优化不会自行创建蒙版。"}
            </p>

            <NoteSection label="方案提示" title="提示" items={plan.warnings} />
            <NoteSection
              label="能力限制"
              title="能力限制"
              items={plan.limitations}
            />
          </>
        )}

        {ready && (
          <ReviewActions
            proposal={proposal}
            canAccept={canAccept}
            dirty={dirty}
            changes={changes}
            noChangesNote={
              proposal.source === "critique"
                ? "这条点评建议没有产生参数变化，接受按钮已停用。"
                : patch !== null
                  ? "这条指令没有产生参数变化，接受按钮已停用。"
                  : "当前照片无需主要调整，接受按钮已停用。"
            }
            onView={onView}
            onAccept={onAccept}
            onAbandon={onAbandon}
          />
        )}

        <FeedbackSection feedback={feedback} />
      </div>
    </section>
  );
}
