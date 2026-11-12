"use client";

import type { ProviderKind } from "@/types/provider-settings";

import type { EntryDraft } from "../provider-draft";
import styles from "../onboarding.module.css";

export interface ProviderStepProps {
  idPrefix: string;
  draft: EntryDraft;
  apiKeyPlaceholder: string;
  keyHint?: string | null;
  disabled: boolean;
  onChange: (patch: Partial<EntryDraft>) => void;
}

export function ProviderStep({
  idPrefix,
  draft,
  apiKeyPlaceholder,
  keyHint,
  disabled,
  onChange,
}: ProviderStepProps) {
  const isMock = draft.provider === "mock";

  const changeProvider = (provider: ProviderKind) => {
    if (provider === draft.provider) {
      return;
    }
    onChange({
      provider,
      model: "",
      baseUrl: "",
      apiKey: "",
    });
  };

  return (
    <div className={styles.fieldGrid}>
      <label className={styles.field} htmlFor={`${idPrefix}-provider`}>
        Provider
        <select
          id={`${idPrefix}-provider`}
          value={draft.provider}
          disabled={disabled}
          onChange={(event) => changeProvider(event.target.value as ProviderKind)}
          className={styles.select}
        >
          <option value="mock">Mock（模拟，无需密钥）</option>
          <option value="openai">OpenAI 兼容</option>
        </select>
      </label>

      <label className={styles.field} htmlFor={`${idPrefix}-model`}>
        模型名
        <input
          id={`${idPrefix}-model`}
          type="text"
          value={draft.model}
          maxLength={200}
          autoComplete="off"
          spellCheck={false}
          placeholder={isMock ? "Mock 不使用模型名" : "例如 qwen-vl-plus / gpt-4o-mini"}
          disabled={disabled || isMock}
          onChange={(event) => onChange({ model: event.target.value })}
          className={styles.input}
        />
      </label>

      <label
        className={`${styles.field} ${styles.fieldWide}`}
        htmlFor={`${idPrefix}-base-url`}
      >
        Base URL
        <input
          id={`${idPrefix}-base-url`}
          type="url"
          value={draft.baseUrl}
          maxLength={1000}
          autoComplete="off"
          spellCheck={false}
          placeholder={isMock ? "Mock 不使用 Base URL" : "https://api.example.com/v1"}
          disabled={disabled || isMock}
          onChange={(event) => onChange({ baseUrl: event.target.value })}
          className={styles.input}
        />
      </label>

      <label
        className={`${styles.field} ${styles.fieldWide}`}
        htmlFor={`${idPrefix}-api-key`}
      >
        API Key
        <input
          id={`${idPrefix}-api-key`}
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
          ? "模拟模型不需要密钥，适合先体验流程；之后可随时在右上角「模型设置」中切换。"
          : "填写支持 OpenAI 协议的服务地址与密钥；也可以先用 Mock 体验流程。"}
      </p>
    </div>
  );
}
