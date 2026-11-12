"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";

import {
  ONBOARDING_SESSION_COOKIE,
  ONBOARDING_SESSION_VALUE,
} from "@/lib/onboarding-cookie";

import { ConfigStage } from "./components/config-stage";
import { FinaleStage } from "./components/finale-stage";
import { IntroStage } from "./components/intro-stage";
import { useReducedMotion } from "./use-reduced-motion";
import styles from "./onboarding.module.css";

type OnboardingStage = "intro" | "config" | "finale";

const COMPLETE_ENDPOINT = "/api/onboarding";

async function completeOnboarding(): Promise<void> {
  const response = await fetch(COMPLETE_ENDPOINT, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ completed: true }),
  });

  if (!response.ok) {
    throw new Error("onboarding_write_failed");
  }
}

function describeCompletionError(error: unknown): string {
  if (error instanceof Error && error.message === "onboarding_write_failed") {
    return "无法写入本机引导状态，请检查数据目录权限后重试。";
  }
  return "无法保存引导状态，请重试。";
}

function clearSessionBypass(): void {
  document.cookie = `${ONBOARDING_SESSION_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax`;
}

export function OnboardingFlow() {
  const router = useRouter();
  const reducedMotion = useReducedMotion();
  const [stage, setStage] = useState<OnboardingStage>("intro");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [modelReady, setModelReady] = useState(false);

  const goToConfig = useCallback(() => {
    setStage("config");
  }, []);

  const finishConfig = useCallback((ready: boolean) => {
    setModelReady(ready);
    setStage("finale");
  }, []);

  const finish = useCallback(async () => {
    if (busy) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await completeOnboarding();
      clearSessionBypass();
      router.replace("/");
    } catch (cause) {
      setError(describeCompletionError(cause));
      setBusy(false);
    }
  }, [busy, router]);

  const enterAnyway = useCallback(() => {
    document.cookie = `${ONBOARDING_SESSION_COOKIE}=${ONBOARDING_SESSION_VALUE}; Path=/; SameSite=Lax`;
    router.replace("/");
  }, [router]);

  return (
    <main className={styles.screen}>
      <div className={styles.aurora} aria-hidden="true" />
      {stage === "intro" && (
        <IntroStage reducedMotion={reducedMotion} onContinue={goToConfig} />
      )}
      {stage === "config" && (
        <ConfigStage
          onComplete={finishConfig}
          onSkip={finishConfig}
        />
      )}
      {stage === "finale" && (
        <FinaleStage
          busy={busy}
          error={error}
          modelReady={modelReady}
          onStart={() => void finish()}
          onEnterAnyway={enterAnyway}
        />
      )}
    </main>
  );
}
