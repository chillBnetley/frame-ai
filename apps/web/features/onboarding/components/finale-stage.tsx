"use client";

import { useEffect, useRef } from "react";

import { ArrowRightIcon, ShieldCheckIcon } from "@/components/icons";

import { BrandMark } from "./brand-mark";
import styles from "../onboarding.module.css";

export interface FinaleStageProps {
  busy: boolean;
  error: string | null;
  modelReady: boolean;
  onStart: () => void;
  onEnterAnyway: () => void;
}

export function FinaleStage({
  busy,
  error,
  modelReady,
  onStart,
  onEnterAnyway,
}: FinaleStageProps) {
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  return (
    <section className={styles.finale} aria-labelledby="onboarding-finale-title">
      <BrandMark className={styles.finaleMark} />
      <p className={styles.finaleKicker}>FRAME AI</p>

      <h1
        ref={headingRef}
        id="onboarding-finale-title"
        tabIndex={-1}
        className={styles.finaleTitle}
      >
        开始你的摄影之旅
      </h1>

      <p className={styles.finaleNote}>
        {modelReady
          ? "视觉与决策模型已就绪，可以开始调整照片了。"
          : "当前使用模拟模型，可随时在右上角「模型设置」中配置。"}
      </p>

      <button
        type="button"
        className={styles.startButton}
        disabled={busy}
        onClick={onStart}
      >
        {busy ? "正在进入…" : "开始"}
        {!busy && <ArrowRightIcon className={styles.startIcon} />}
      </button>

      {error !== null && (
        <>
          <p role="alert" className={styles.error}>
            {error}
          </p>
          <button
            type="button"
            className={styles.fallbackButton}
            onClick={onEnterAnyway}
          >
            仍然进入（本次有效）
          </button>
        </>
      )}

      <p className={styles.privacy}>
        <ShieldCheckIcon className={styles.privacyIcon} />
        图片与密钥只保存在本机
      </p>
    </section>
  );
}
