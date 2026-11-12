"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  AlertTriangleIcon,
  ArrowRightIcon,
  CheckCircleIcon,
  RefreshIcon,
} from "@/components/icons";
import {
  fetchProviderSettings,
  saveProviderSettings,
  testProviderSettings,
} from "@/lib/api/settings";
import type {
  ProviderSettingsView,
  ProviderTestResult,
} from "@/types/provider-settings";

import { GenerativeStep } from "./generative-step";
import { ProviderStep } from "./provider-step";
import {
  areModelsReady,
  createEntryDraft,
  createGenerativeDraft,
  describeProviderError,
  entryUpdate,
  generativeUpdate,
  keyPlaceholder,
  validateEntryDraft,
  validateGenerativeDraft,
  type EntryDraft,
  type GenerativeDraft,
} from "../provider-draft";
import styles from "../onboarding.module.css";

const STEP_META = [
  {
    key: "vision",
    label: "视觉",
    title: "视觉模型",
    description: "让 AI 看懂照片的场景、主体与光线。",
  },
  {
    key: "decision",
    label: "决策",
    title: "决策模型",
    description: "决定曝光、色彩与风格调整。可与视觉模型共用连接，也可单独配置。",
  },
  {
    key: "generative",
    label: "图像",
    title: "生成式图像",
    description: "扩图、智能消除与局部生成。可选，不影响基础调整。",
  },
] as const;

type StepIndex = 0 | 1 | 2;

interface Feedback {
  tone: "error" | "success" | "info";
  message: string;
}

export interface ConfigStageProps {
  onComplete: (modelsReady: boolean) => void;
  onSkip: (modelsReady: boolean) => void;
}

export function ConfigStage({ onComplete, onSkip }: ConfigStageProps) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [view, setView] = useState<ProviderSettingsView | null>(null);
  const [vision, setVision] = useState<EntryDraft | null>(null);
  const [decision, setDecision] = useState<EntryDraft | null>(null);
  const [generative, setGenerative] = useState<GenerativeDraft | null>(null);
  const [step, setStep] = useState<StepIndex>(0);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"save" | "test" | null>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [testResult, setTestResult] = useState<ProviderTestResult | null>(null);
  const [sharedKey, setSharedKey] = useState("");
  const [decisionFollowsVision, setDecisionFollowsVision] = useState(true);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setLoadError(null);
    try {
      const next = await fetchProviderSettings(signal);
      if (signal?.aborted) {
        return;
      }
      setView(next);
      setVision(createEntryDraft(next.vision));
      setDecision(createEntryDraft(next.decision));
      setGenerative(createGenerativeDraft(next.generative));
      setDecisionFollowsVision(next.decision.provider === "mock");
      setStep(0);
    } catch (error) {
      if (signal?.aborted) {
        return;
      }
      setLoadError(describeProviderError(error));
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    queueMicrotask(() => {
      void load(controller.signal);
    });
    return () => controller.abort();
  }, [load]);

  useEffect(() => {
    headingRef.current?.focus();
  }, [step, loading, loadError]);

  const clearFeedback = () => {
    setFeedback(null);
    setTestResult(null);
  };

  const updateVision = (patch: Partial<EntryDraft>) => {
    setVision((current) => (current ? { ...current, ...patch } : current));
    if (patch.provider !== undefined || patch.baseUrl !== undefined) {
      setSharedKey("");
    }
    clearFeedback();
  };

  const updateDecision = (patch: Partial<EntryDraft>) => {
    setDecision((current) => {
      if (!current) {
        return current;
      }
      const base =
        decisionFollowsVision && vision
          ? {
              ...current,
              provider: vision.provider,
              model: vision.model,
              baseUrl: vision.baseUrl,
            }
          : current;
      return { ...base, ...patch };
    });
    if (
      patch.provider !== undefined ||
      patch.model !== undefined ||
      patch.baseUrl !== undefined
    ) {
      setDecisionFollowsVision(false);
    }
    clearFeedback();
  };

  const updateGenerative = (patch: Partial<GenerativeDraft>) => {
    setGenerative((current) => (current ? { ...current, ...patch } : current));
    clearFeedback();
  };

  const followVision = () => {
    if (!vision || !decision) {
      return;
    }
    setDecision({
      ...decision,
      provider: vision.provider,
      model: vision.model,
      baseUrl: vision.baseUrl,
    });
    setDecisionFollowsVision(true);
    clearFeedback();
  };

  const enterStep = (next: StepIndex) => {
    clearFeedback();
    if (next === 1 && vision && decisionFollowsVision) {
      setDecision((current) =>
        current
          ? {
              ...current,
              provider: vision.provider,
              model: vision.model,
              baseUrl: vision.baseUrl,
            }
          : {
              provider: vision.provider,
              model: vision.model,
              baseUrl: vision.baseUrl,
              apiKey: "",
            },
      );
    }
    setStep(next);
  };

  const saveVision = async () => {
    if (!view || !vision) {
      return;
    }
    const validation = validateEntryDraft(vision, {
      label: "视觉模型",
      hasSavedKey: view.vision.hasApiKey,
    });
    if (validation) {
      setFeedback({ tone: "error", message: validation });
      return;
    }

    const update = entryUpdate(vision, view.vision);
    if (Object.keys(update).length === 0) {
      enterStep(1);
      return;
    }

    setBusy("save");
    setFeedback(null);
    setTestResult(null);
    try {
      const next = await saveProviderSettings({ vision: update });
      const typedKey = vision.apiKey.trim();
      if (typedKey !== "") {
        setSharedKey(typedKey);
      }
      setView(next);
      setVision(createEntryDraft(next.vision));
      enterStep(1);
    } catch (error) {
      setFeedback({ tone: "error", message: describeProviderError(error) });
    } finally {
      setBusy(null);
    }
  };

  const decisionDraft = (): EntryDraft | null => {
    if (!decision || !vision) {
      return null;
    }
    if (!decisionFollowsVision) {
      return decision;
    }
    return {
      ...decision,
      provider: vision.provider,
      model: vision.model,
      baseUrl: vision.baseUrl,
    };
  };

  const decisionKeyFallback = (draft: EntryDraft | null): string => {
    if (!draft || !vision) {
      return "";
    }
    return draft.provider === vision.provider &&
      draft.baseUrl.trim() === vision.baseUrl.trim()
      ? sharedKey
      : "";
  };

  const saveDecision = async () => {
    if (!view) {
      return;
    }
    const draft = decisionDraft();
    if (!draft) {
      return;
    }
    const fallback = decisionKeyFallback(draft);
    const validation = validateEntryDraft(draft, {
      label: "决策模型",
      hasSavedKey: view.decision.hasApiKey,
      apiKeyFallback: fallback,
    });
    if (validation) {
      setFeedback({ tone: "error", message: validation });
      return;
    }

    const update = entryUpdate(draft, view.decision, fallback);
    if (Object.keys(update).length === 0) {
      enterStep(2);
      return;
    }

    setBusy("save");
    setFeedback(null);
    setTestResult(null);
    try {
      const next = await saveProviderSettings({ decision: update });
      setView(next);
      setDecision(createEntryDraft(next.decision));
      enterStep(2);
    } catch (error) {
      setFeedback({ tone: "error", message: describeProviderError(error) });
    } finally {
      setBusy(null);
    }
  };

  const saveGenerative = async () => {
    if (!view || !generative) {
      return;
    }
    const validation = validateGenerativeDraft(generative, {
      hasSavedKey: view.generative.hasApiKey,
    });
    if (validation) {
      setFeedback({ tone: "error", message: validation });
      return;
    }

    const update = generativeUpdate(generative, view.generative);
    if (Object.keys(update).length === 0) {
      onComplete(areModelsReady(view));
      return;
    }

    setBusy("save");
    setFeedback(null);
    setTestResult(null);
    try {
      const next = await saveProviderSettings({ generative: update });
      setView(next);
      onComplete(areModelsReady(next));
    } catch (error) {
      setFeedback({ tone: "error", message: describeProviderError(error) });
    } finally {
      setBusy(null);
    }
  };

  const handleNext = () => {
    if (busy !== null) {
      return;
    }
    if (step === 0) {
      void saveVision();
    } else if (step === 1) {
      void saveDecision();
    } else {
      void saveGenerative();
    }
  };

  const handleBack = () => {
    if (busy !== null || step === 0) {
      return;
    }
    clearFeedback();
    setStep((current) => (current === 2 ? 1 : 0));
  };

  const handleTest = async () => {
    if (busy !== null || !view) {
      return;
    }
    const draft = decisionDraft();
    const fallback = decisionKeyFallback(draft);
    const validation =
      step === 0 && vision
        ? validateEntryDraft(vision, {
            label: "视觉模型",
            hasSavedKey: view.vision.hasApiKey,
          })
        : step === 1 && draft
          ? validateEntryDraft(draft, {
              label: "决策模型",
              hasSavedKey: view.decision.hasApiKey,
              apiKeyFallback: fallback,
            })
          : step === 2 && generative
            ? validateGenerativeDraft(generative, {
                hasSavedKey: view.generative.hasApiKey,
              })
            : null;
    if (validation) {
      setFeedback({ tone: "error", message: validation });
      return;
    }
    const update =
      step === 0 && vision
        ? { vision: entryUpdate(vision, view.vision) }
        : step === 1 && draft
          ? { decision: entryUpdate(draft, view.decision, fallback) }
          : step === 2 && generative
            ? { generative: generativeUpdate(generative, view.generative) }
            : null;
    if (!update) {
      return;
    }

    setBusy("test");
    setFeedback(null);
    setTestResult(null);
    try {
      const results = await testProviderSettings(update);
      setTestResult(results[STEP_META[step].key]);
      setFeedback({
        tone: "info",
        message: "连接测试完成。测试只发送文本提示，不会上传图片。",
      });
    } catch (error) {
      setFeedback({ tone: "error", message: describeProviderError(error) });
    } finally {
      setBusy(null);
    }
  };

  const handleSkip = () => {
    if (busy !== null) {
      return;
    }
    onSkip(areModelsReady(view));
  };

  const meta = STEP_META[step];
  const isMockVision = vision?.provider === "mock";
  const decisionDraftValue = decisionDraft();
  const decisionUsesSharedKey =
    decisionDraftValue !== null &&
    vision !== null &&
    decisionDraftValue.provider === vision.provider &&
    decisionDraftValue.baseUrl.trim() === vision.baseUrl.trim() &&
    sharedKey !== "";
  const decisionKeyHint =
    view !== null &&
    vision !== null &&
    view.vision.hasApiKey &&
    sharedKey === "" &&
    view.decision.apiKeySource === "none" &&
    decisionDraftValue?.provider !== "mock"
      ? "视觉模型的密钥已保存在本机，但不会回显；决策模型需要再填写一次。"
      : null;

  return (
    <section
      className={styles.config}
      aria-labelledby="onboarding-config-title"
      aria-busy={busy !== null || loading}
    >
      <div className={styles.configHeader}>
        <div>
          <p className={styles.configKicker}>STEP {step + 1} OF 3</p>
          <h1
            ref={headingRef}
            id="onboarding-config-title"
            tabIndex={-1}
            className={styles.configTitle}
          >
            {meta.title}
          </h1>
          <p className={styles.configDescription}>{meta.description}</p>
        </div>
        {step !== 1 && (
          <button
            type="button"
            className={styles.configSkip}
            disabled={busy !== null}
            onClick={handleSkip}
          >
            暂不配置
          </button>
        )}
      </div>

      <ol className={styles.progress} aria-label="模型配置进度">
        {STEP_META.map((item, index) => (
          <li
            key={item.key}
            className={`${styles.progressItem} ${
              index === step ? styles.progressActive : ""
            } ${index < step ? styles.progressDone : ""}`}
            aria-current={index === step ? "step" : undefined}
          >
            <span className={styles.progressDot} aria-hidden="true">
              {index < step ? "✓" : index + 1}
            </span>
            <span className={styles.progressLabel}>{item.label}</span>
          </li>
        ))}
      </ol>

      {loading && view === null && (
        <p role="status" aria-live="polite" className={styles.loadState}>
          正在读取当前配置…
        </p>
      )}

      {loadError !== null && view === null && (
        <div className={styles.loadError}>
          <p role="alert" className={styles.loadErrorText}>
            <AlertTriangleIcon className={styles.inlineIcon} />
            {loadError}
          </p>
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={() => void load()}
          >
            <RefreshIcon className={styles.inlineIcon} />
            重新读取
          </button>
        </div>
      )}

      {view !== null && vision !== null && decision !== null && generative !== null && (
        <>
          {step === 0 && (
            <ProviderStep
              idPrefix="vision"
              draft={vision}
              apiKeyPlaceholder={keyPlaceholder(view.vision.apiKeySource)}
              disabled={busy !== null}
              onChange={updateVision}
            />
          )}

          {step === 1 && (
            <>
              {view.decision.provider === "mock" && (
                <div className={styles.followRow}>
                  <p>
                    默认沿用第 1 步的连接与模型。也可以单独填写另一套配置。
                  </p>
                  <button
                    type="button"
                    className={styles.inlineButton}
                    disabled={busy !== null || decisionFollowsVision}
                    onClick={followVision}
                  >
                    沿用视觉模型
                  </button>
                </div>
              )}
              <ProviderStep
                idPrefix="decision"
                draft={decisionDraftValue ?? decision}
                apiKeyPlaceholder={
                  decisionUsesSharedKey
                    ? "已使用上一步输入的密钥，留空沿用"
                    : keyPlaceholder(view.decision.apiKeySource)
                }
                keyHint={decisionKeyHint}
                disabled={busy !== null}
                onChange={updateDecision}
              />
            </>
          )}

          {step === 2 && (
            <GenerativeStep
              draft={generative}
              apiKeyPlaceholder={keyPlaceholder(view.generative.apiKeySource)}
              disabled={busy !== null}
              onChange={updateGenerative}
            />
          )}

          {feedback !== null && (
            <p
              role={feedback.tone === "error" ? "alert" : "status"}
              aria-live="polite"
              className={`${styles.feedback} ${
                feedback.tone === "error"
                  ? styles.feedbackError
                  : feedback.tone === "success"
                    ? styles.feedbackSuccess
                    : styles.feedbackInfo
              }`}
            >
              {feedback.message}
            </p>
          )}

          {testResult !== null && (
            <p
              role="status"
              aria-live="polite"
              className={`${styles.testResult} ${
                testResult.ok ? styles.testResultOk : styles.testResultError
              }`}
            >
              {testResult.ok ? (
                <CheckCircleIcon className={styles.inlineIcon} />
              ) : (
                <AlertTriangleIcon className={styles.inlineIcon} />
              )}
              {testResult.ok
                ? `连接正常（${testResult.latencyMs} ms）`
                : `连接失败（${testResult.code ?? "provider_test_failed"}）${
                    testResult.message ? `：${testResult.message}` : ""
                  }`}
            </p>
          )}

          <div className={styles.configFooter}>
            <div className={styles.footerLeft}>
              {step > 0 && (
                <button
                  type="button"
                  className={styles.secondaryButton}
                  disabled={busy !== null}
                  onClick={handleBack}
                >
                  上一步
                </button>
              )}
              {isMockVision && step === 1 && (
                <span className={styles.mockNote}>当前视觉模型为模拟模式</span>
              )}
            </div>
            <div className={styles.footerRight}>
              <button
                type="button"
                className={styles.secondaryButton}
                disabled={busy !== null}
                onClick={() => void handleTest()}
              >
                <RefreshIcon className={styles.inlineIcon} />
                {busy === "test" ? "正在测试…" : "测试连接"}
              </button>
              <button
                type="button"
                className={styles.primaryButton}
                disabled={busy !== null}
                onClick={handleNext}
              >
                {busy === "save" ? "正在保存…" : step === 2 ? "完成" : "下一步"}
                {busy === null && step < 2 && (
                  <ArrowRightIcon className={styles.buttonIcon} />
                )}
              </button>
            </div>
          </div>

          <p className={styles.configNote}>
            API Key 加密保存在本机数据目录，不会回显到页面或日志。
          </p>
        </>
      )}

      {view === null && loading === false && loadError !== null && (
        <div className={styles.configFooter}>
          <div className={styles.footerLeft} />
          <div className={styles.footerRight}>
            <button
              type="button"
              className={styles.primaryButton}
              onClick={() => onSkip(false)}
            >
              暂不配置，进入下一步
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
