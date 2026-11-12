"use client";

import type { GenerativeProviderKind } from "@/types/provider-settings";

import type { GenerativeDraft } from "../provider-draft";
import styles from "../onboarding.module.css";

const DEFAULT_GENERATIVE_MODEL = "wanx2.1-imageedit";

export interface GenerativeStepProps {
  draft: GenerativeDraft;
  apiKeyPlaceholder: string;
  keyHint?: string | null;
  disabled: boolean;
  onChange: (patch: Partial<GenerativeDraft>) => void;
}

export function GenerativeStep({
  draft,
  apiKeyPlaceholder,
  keyHint,
  disabled,
  onChange,
}: GenerativeStepProps) {
  const isMock = draft.provider === "mock";

  const changeProvider = (provider: GenerativeProviderKind) => {
    if (provider === draft.provider) {
      return;
    }
    onChange({
      provider,
      model:
        provider === "dashscope" && draft.model.trim() === ""
          ? DEFAULT_GENERATIVE_MODEL
          : draft.model,
      apiKey: "",
    });
  };

  return (
    <div className={styles.fieldGrid}>
      <label className={styles.field} htmlFor="generative-provider">
        Provider
        <select
          id="generative-provider"
          value={draft.provider}
          disabled={disabled}
          onChange={(event) =>
            changeProvider(event.target.value as GenerativeProviderKind)
          }
          className={styles.select}
        >
          <option value="mock">Mock（模拟，不上传）</option>
          <option value="dashscope">通义万相 wanx2.1-imageedit</option>
        </select>
      </label>

      <label className={styles.field} htmlFor="generative-model">
        模型名
        <input
          id="generative-model"
          type="text"
          value={draft.model}
          maxLength={200}
          autoComplete="off"
          spellCheck={false}
          placeholder={isMock ? "Mock 不使用模型名" : DEFAULT_GENERATIVE_MODEL}
          disabled={disabled || isMock}
          onChange={(event) => onChange({ model: event.target.value })}
          className={styles.input}
        />
      </label>

      <label
        className={`${styles.field} ${styles.fieldWide}`}
        htmlFor="generative-api-key"
      >
        API Key（百炼）
        <input
          id="generative-api-key"
          type="password"
          value={draft.apiKey}
          maxLength={8192}
          autoComplete="new-password"
          spellCheck={false}
          placeholder={isMock ? "Mock 不使用 API Key" : apiKeyPlaceholder}
          disabled={disabled || isMock}
          onChange={(event) => onChange({ apiKey: event.target.value })}
          className={styles.input}
        />
        {keyHint && !isMock ? (
          <span className={styles.fieldHint}>{keyHint}</span>
        ) : null}
      </label>

      <p className={`${styles.fieldNote} ${styles.fieldWide}`}>
        {isMock
          ? "模拟生成不会上传图片，适合先体验流程；之后可随时在右上角「模型设置」中切换。"
          : "扩图、智能消除与局部生成会把画面上传到阿里云百炼；结果链接 24 小时有效，任务数据 24 小时后清理。"}
      </p>

      <details className={`${styles.advanced} ${styles.fieldWide}`}>
        <summary>高级选项</summary>
        <div className={styles.advancedBody}>
          <label className={styles.field} htmlFor="generative-daily-limit">
            每日最多生成（张，0 为不限）
            <input
              id="generative-daily-limit"
              type="number"
              min={0}
              max={1000}
              value={draft.dailyImageLimit}
              disabled={disabled || isMock}
              onChange={(event) => onChange({ dailyImageLimit: event.target.value })}
              className={styles.input}
            />
          </label>
        </div>
      </details>
    </div>
  );
}
