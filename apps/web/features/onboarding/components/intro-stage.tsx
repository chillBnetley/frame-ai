"use client";

import { useEffect } from "react";

import { ArrowRightIcon } from "@/components/icons";

import { BrandMark } from "./brand-mark";
import styles from "../onboarding.module.css";

export const INTRO_AUTO_ADVANCE_MS = 3200;

export interface IntroStageProps {
  reducedMotion: boolean;
  onContinue: () => void;
}

export function IntroStage({ reducedMotion, onContinue }: IntroStageProps) {
  useEffect(() => {
    if (reducedMotion) {
      return;
    }
    const timer = window.setTimeout(onContinue, INTRO_AUTO_ADVANCE_MS);
    return () => window.clearTimeout(timer);
  }, [onContinue, reducedMotion]);

  return (
    <section className={styles.intro} aria-labelledby="onboarding-intro-title">
      <div className={styles.tile}>
        <span className={styles.halo} aria-hidden="true" />
        <BrandMark className={styles.heroMark} />
      </div>

      <p className={styles.wordmark}>FRAME AI</p>
      <span className={styles.rule} aria-hidden="true" />

      <h1 id="onboarding-intro-title" className={styles.tagline}>
        私人 AI 摄影大师
      </h1>

      <button
        type="button"
        className={styles.continueButton}
        onClick={onContinue}
      >
        继续
        <ArrowRightIcon className={styles.continueIcon} />
      </button>
    </section>
  );
}
