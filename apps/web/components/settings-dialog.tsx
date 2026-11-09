"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { AlertTriangleIcon, CheckCircleIcon, RefreshIcon, SettingsIcon } from "@/components/icons";
import { ApiClientError } from "@/lib/api/client";
import {
  fetchProviderSettings,
  resetProviderSettings,
  saveProviderSettings,
  testProviderSettings,
} from "@/lib/api/settings";
import { validationFields } from "@/lib/error-messages";
import type {
  ApiKeySource,
  ProviderEntryUpdate,
  ProviderKind,
  ProviderSettingsUpdate,
  ProviderSettingsView,
  ProviderTestResponse,
} from "@/types/provider-settings";

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

const SECTIONS = ["vision", "decision", "planner"] as const;

type ProviderSection = (typeof SECTIONS)[number];

interface EntryForm {
  provider: ProviderKind;
  model: string;
  baseUrl: string;
  apiKey: string;
  clearApiKey: boolean;
}

type FormState = Record<ProviderSection, EntryForm>;

interface Feedback {
  tone: "success" | "error" | "info";
  message: string;
}

const SECTION_LABELS: Record<ProviderSection, string> = {
  vision: "视觉模型",
  decision: "决策模型",
  planner: "规划模型（可选）",
};

const KEY_SOURCE_LABELS: Record<ApiKeySource, string> = {
  saved: "本地保存",
  environment: "环境变量",
  none: "未配置",
};

function toForm(view: ProviderSettingsView): FormState {
  const entry = (section: ProviderSection): EntryForm => ({
    provider: view[section].provider,
    model: view[section].model,
    baseUrl: view[section].baseUrl,
    apiKey: "",
    clearApiKey: false,
  });
  return { vision: entry("vision"), decision: entry("decision"), planner: entry("planner") };
}

function toUpdate(form: FormState, view: ProviderSettingsView): ProviderSettingsUpdate {
  const update: ProviderSettingsUpdate = {};
  for (const section of SECTIONS) {
    const entry = form[section];
    const current = view[section];
    const patch: ProviderEntryUpdate = {};
    if (entry.provider !== current.provider) {
      patch.provider = entry.provider;
    }
    if (entry.model !== current.model) {
      patch.model = entry.model;
    }
    if (entry.baseUrl !== current.baseUrl) {
      patch.baseUrl = entry.baseUrl;
    }
    if (entry.clearApiKey && current.apiKeySource === "saved") {
      patch.clearApiKey = true;
    } else if (entry.apiKey !== "") {
      patch.apiKey = entry.apiKey;
    }
    if (Object.keys(patch).length > 0) {
      update[section] = patch;
    }
  }
  return update;
}

function describeSettingsError(error: unknown): string {
  if (error instanceof ApiClientError) {
    if (error.code === "invalid_provider_settings") {
      const fields = validationFields(error.details);
      return fields.length > 0
        ? `配置不完整或格式不正确：${fields.join("、")}`
        : "配置不完整或格式不正确，请检查所有字段。";
    }
    if (error.code === "provider_settings_unavailable") {
      return "设置服务尚未就绪，请稍后重试。";
    }
    if (error.code === "provider_settings_write_failed") {
      return "配置无法写入本机数据目录，请检查磁盘权限。";
    }
    return error.message;
  }
  return error instanceof Error ? error.message : "设置操作失败，请稍后重试。";
}

function keyPlaceholder(source: ApiKeySource): string {
  if (source === "saved") {
    return "已从本地保存，留空保持不变";
  }
  if (source === "environment") {
    return "使用环境变量中的密钥，留空保持不变";
  }
  return "sk-…";
}

export interface SettingsDialogProps {
  open: boolean;
  onClose: () => void;
}

export function SettingsDialog({ open, onClose }: SettingsDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);

  const [view, setView] = useState<ProviderSettingsView | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"save" | "test" | "reset" | null>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [testResults, setTestResults] = useState<ProviderTestResponse | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  const load = useCallback(async (signal?: AbortSignal) => {
    await Promise.resolve();
    if (signal?.aborted) {
      return;
    }
    setFeedback(null);
    setTestResults(null);
    setConfirmReset(false);
    setLoading(true);
    setLoadError(null);
    try {
      const next = await fetchProviderSettings(signal);
      setView(next);
      setForm(toForm(next));
    } catch (error) {
      if (signal?.aborted) {
        return;
      }
      setLoadError(describeSettingsError(error));
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    if (!open) {
      return;
    }
    const controller = new AbortController();
    queueMicrotask(() => {
      void load(controller.signal);
    });
    return () => controller.abort();
  }, [load, open]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const previous =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const node = dialogRef.current;
    node?.querySelector<HTMLElement>("[data-autofocus]")?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !node) {
        return;
      }
      const focusable = Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (focusable.length === 0) {
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previous?.focus();
    };
  }, [open]);

  const ready = form !== null;
  useEffect(() => {
    if (!open || !ready) {
      return;
    }
    dialogRef.current?.querySelector<HTMLElement>("[data-autofocus]")?.focus();
  }, [open, ready]);

  if (!open) {
    return null;
  }

  const disabled = busy !== null;

  const updateEntry = (section: ProviderSection, patch: Partial<EntryForm>) => {
    setForm((current) =>
      current ? { ...current, [section]: { ...current[section], ...patch } } : current,
    );
  };

  const handleSave = async () => {
    if (!form || !view) {
      return;
    }
    const update = toUpdate(form, view);
    if (Object.keys(update).length === 0) {
      setFeedback({ tone: "info", message: "没有需要保存的更改。" });
      return;
    }
    setBusy("save");
    setFeedback(null);
    try {
      const next = await saveProviderSettings(update);
      setView(next);
      setForm(toForm(next));
      setTestResults(null);
      setConfirmReset(false);
      setFeedback({
        tone: "success",
        message: "已保存并应用。新的分析任务将使用该配置。",
      });
    } catch (error) {
      setFeedback({ tone: "error", message: describeSettingsError(error) });
    } finally {
      setBusy(null);
    }
  };

  const handleTest = async () => {
    if (!form || !view) {
      return;
    }
    setBusy("test");
    setFeedback(null);
    setTestResults(null);
    try {
      const results = await testProviderSettings(toUpdate(form, view));
      setTestResults(results);
      setFeedback({
        tone: "info",
        message: "连接测试完成。测试只发送文本提示，不会上传图片。",
      });
    } catch (error) {
      setFeedback({ tone: "error", message: describeSettingsError(error) });
    } finally {
      setBusy(null);
    }
  };

  const handleReset = async () => {
    setBusy("reset");
    setFeedback(null);
    try {
      const next = await resetProviderSettings();
      setView(next);
      setForm(toForm(next));
      setTestResults(null);
      setConfirmReset(false);
      setFeedback({ tone: "success", message: "已恢复环境变量配置。" });
    } catch (error) {
      setFeedback({ tone: "error", message: describeSettingsError(error) });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-black/70 p-4 backdrop-blur-sm">
      <div className="flex min-h-full items-start justify-center">
        <div
          ref={dialogRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby="settings-dialog-title"
          aria-describedby="settings-dialog-description"
          className="my-auto w-full max-w-2xl rounded-2xl border border-white/12 bg-[#101113] p-5 shadow-[0_30px_80px_-20px_rgba(0,0,0,0.9)]"
        >
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-2.5">
            <span className="mt-0.5 grid size-7 place-items-center rounded-md border border-white/12 bg-white/[0.04] text-accent">
              <SettingsIcon className="size-4" />
            </span>
            <div>
              <h2 id="settings-dialog-title" className="text-sm font-medium text-white">
                模型设置
              </h2>
              <p id="settings-dialog-description" className="mt-1 text-[11px] text-white/40">
                配置本地 AI Provider。保存后立即热替换，新任务生效，运行中的任务不受影响。
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => onCloseRef.current()}
            aria-label="关闭模型设置"
            className="grid size-11 place-items-center rounded-lg text-white/45 transition-colors hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            <span aria-hidden="true">✕</span>
          </button>
        </div>

        {loading && !form && (
          <p role="status" aria-live="polite" className="mt-6 text-xs text-white/50">
            正在读取当前配置…
          </p>
        )}

        {loadError && !form && (
          <div className="mt-4 rounded-lg border border-red-300/25 bg-red-400/[0.08] px-3 py-2.5">
            <p role="alert" className="flex items-start gap-2 text-xs text-red-100/90">
              <AlertTriangleIcon className="mt-0.5 size-3.5 shrink-0" />
              {loadError}
            </p>
            <button
              type="button"
              onClick={() => void load()}
              className="mt-2 inline-flex min-h-9 items-center gap-1.5 rounded-md border border-white/12 px-2.5 text-[11px] text-white/65 transition-colors hover:bg-white/[0.05] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              <RefreshIcon className="size-3.5" />
              重新读取
            </button>
          </div>
        )}

        {form && view && (
          <>
            <div className="mt-4 grid gap-3">
              {SECTIONS.map((section) => {
                const entry = form[section];
                const current = view[section];
                const isMock = entry.provider === "mock";
                const label = SECTION_LABELS[section];
                return (
                  <fieldset
                    key={section}
                    className="rounded-xl border border-white/10 bg-white/[0.02] p-3"
                  >
                    <legend className="px-1 text-xs text-white/60">{label}</legend>
                    {section === "planner" && (
                      <p className="mt-1 text-[10px] text-white/35">
                        留空即跟随决策模型；只有填写的字段会覆盖决策模型。
                      </p>
                    )}
                    <div className="grid gap-3 sm:grid-cols-2">
                      <label className="grid gap-1 text-[11px] text-white/55" htmlFor={`${section}-provider`}>
                        Provider
                        <select
                          id={`${section}-provider`}
                          value={entry.provider}
                          disabled={disabled}
                          data-autofocus={section === "vision" ? true : undefined}
                          onChange={(event) =>
                            updateEntry(section, {
                              provider: event.target.value as ProviderKind,
                              model: "",
                              apiKey: "",
                              clearApiKey: false,
                            })
                          }
                          className="min-h-11 rounded-lg border border-white/12 bg-black/35 px-2.5 text-xs text-white/85 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40"
                        >
                          <option value="mock">Mock（开发/测试）</option>
                          <option value="openai">OpenAI 兼容</option>
                        </select>
                      </label>

                      <label className="grid gap-1 text-[11px] text-white/55" htmlFor={`${section}-model`}>
                        模型名
                        <input
                          id={`${section}-model`}
                          type="text"
                          value={entry.model}
                          maxLength={200}
                          autoComplete="off"
                          placeholder={isMock ? "Mock 不使用模型名" : "例如 gpt-4o-mini"}
                          disabled={disabled || isMock}
                          onChange={(event) => updateEntry(section, { model: event.target.value })}
                          className="min-h-11 rounded-lg border border-white/12 bg-black/35 px-2.5 font-mono text-xs text-white/85 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40"
                        />
                      </label>
                    </div>

                    <label
                      className="mt-3 grid gap-1 text-[11px] text-white/55"
                      htmlFor={`${section}-base-url`}
                    >
                      Base URL
                      <input
                        id={`${section}-base-url`}
                        type="url"
                        value={entry.baseUrl}
                        maxLength={1000}
                        autoComplete="off"
                        spellCheck={false}
                        placeholder={isMock ? "Mock 不使用 Base URL" : "https://api.example.com/v1"}
                        disabled={disabled || isMock}
                        onChange={(event) => updateEntry(section, { baseUrl: event.target.value })}
                        className="min-h-11 rounded-lg border border-white/12 bg-black/35 px-2.5 font-mono text-xs text-white/85 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40"
                      />
                    </label>

                    <label
                      className="mt-3 grid gap-1 text-[11px] text-white/55"
                      htmlFor={`${section}-api-key`}
                    >
                      API Key
                      <input
                        id={`${section}-api-key`}
                        type="password"
                        value={entry.apiKey}
                        maxLength={8192}
                        autoComplete="new-password"
                        spellCheck={false}
                        placeholder={
                          isMock ? "Mock 不使用 API Key" : keyPlaceholder(current.apiKeySource)
                        }
                        disabled={disabled || isMock}
                        onChange={(event) =>
                          updateEntry(section, {
                            apiKey: event.target.value,
                            clearApiKey: false,
                          })
                        }
                        className="min-h-11 rounded-lg border border-white/12 bg-black/35 px-2.5 font-mono text-xs text-white/85 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40"
                      />
                    </label>

                    <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                      <p className="text-[10px] text-white/35">
                        当前生效：{current.model || "—"} · 密钥来源：
                        {KEY_SOURCE_LABELS[current.apiKeySource]}
                      </p>
                      {current.apiKeySource === "saved" && (
                        <label className="inline-flex items-center gap-1.5 text-[11px] text-white/50">
                          <input
                            type="checkbox"
                            checked={entry.clearApiKey}
                            disabled={disabled || isMock}
                            onChange={(event) =>
                              updateEntry(section, {
                                clearApiKey: event.target.checked,
                                apiKey: event.target.checked ? "" : entry.apiKey,
                              })
                            }
                            className="accent-[#d8ff5f]"
                          />
                          清除已保存密钥
                        </label>
                      )}
                    </div>
                  </fieldset>
                );
              })}
            </div>

            <p className="mt-3 text-[10px] text-white/35">
              API Key 加密后保存在本机数据目录，不会回显到页面或日志；本机同一系统用户下的进程仍可能通过系统密钥库解密。
            </p>

            {testResults && (
              <div
                role="status"
                aria-live="polite"
                className="mt-3 grid gap-1.5 rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2.5"
              >
                {SECTIONS.map((section) => {
                  const result = testResults[section];
                  return (
                    <p
                      key={section}
                      className={`flex items-start gap-1.5 text-[11px] ${
                        result.ok ? "text-accent/90" : "text-red-200/90"
                      }`}
                    >
                      {result.ok ? (
                        <CheckCircleIcon className="mt-0.5 size-3.5 shrink-0" />
                      ) : (
                        <AlertTriangleIcon className="mt-0.5 size-3.5 shrink-0" />
                      )}
                      {SECTION_LABELS[section]}：
                      {result.ok
                        ? `连接正常（${result.latencyMs} ms）`
                        : `连接失败（${result.code ?? "provider_test_failed"}）${
                            result.message ? `：${result.message}` : ""
                          }`}
                    </p>
                  );
                })}
              </div>
            )}

            {feedback && (
              <p
                role={feedback.tone === "error" ? "alert" : "status"}
                aria-live="polite"
                className={`mt-3 rounded-lg border px-3 py-2 text-[11px] ${
                  feedback.tone === "error"
                    ? "border-red-300/25 bg-red-400/[0.08] text-red-100/90"
                    : feedback.tone === "success"
                      ? "border-accent/20 bg-accent/[0.05] text-accent/90"
                      : "border-white/10 bg-white/[0.03] text-white/55"
                }`}
              >
                {feedback.message}
              </p>
            )}

            {confirmReset && (
              <div className="mt-3 rounded-lg border border-amber-300/25 bg-amber-300/10 px-3 py-2.5">
                <p className="text-[11px] text-amber-950">
                  恢复后将删除本地保存的模型配置，并重新使用 .env 中的设置。
                </p>
                <div className="mt-2 flex items-center gap-2">
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => void handleReset()}
                    className="min-h-9 rounded-md bg-amber-200 px-2.5 text-[11px] font-medium text-[#241c04] transition-colors hover:bg-amber-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40"
                  >
                    确认恢复
                  </button>
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => setConfirmReset(false)}
                    className="min-h-9 rounded-md border border-white/12 px-2.5 text-[11px] text-white/60 transition-colors hover:bg-white/[0.05] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40"
                  >
                    取消
                  </button>
                </div>
              </div>
            )}

            <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
              <button
                type="button"
                disabled={disabled || !view.hasSavedOverrides}
                onClick={() => setConfirmReset(true)}
                className="min-h-11 rounded-lg border border-white/12 px-3 text-[11px] text-white/55 transition-colors hover:bg-white/[0.05] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-35"
              >
                恢复环境变量配置
              </button>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => void handleTest()}
                  className="inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-white/12 px-3 text-xs text-white/70 transition-colors hover:bg-white/[0.05] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <RefreshIcon className="size-3.5" />
                  {busy === "test" ? "正在测试…" : "测试连接"}
                </button>
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => void handleSave()}
                  className="inline-flex min-h-11 items-center gap-1.5 rounded-lg bg-accent px-4 text-xs font-semibold text-[#101208] transition-colors hover:bg-accent/85 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {busy === "save" ? "正在保存…" : "保存并应用"}
                </button>
              </div>
            </div>
          </>
        )}
        </div>
      </div>
    </div>
  );
}
