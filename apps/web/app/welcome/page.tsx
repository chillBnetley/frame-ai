import type { Metadata } from "next";

import { OnboardingFlow } from "@/features/onboarding/onboarding-flow";

export const metadata: Metadata = {
  title: "FRAME AI · 私人 AI 摄影大师",
  description: "首次使用引导：了解 FRAME AI，配置模型，开始你的摄影之旅。",
  robots: { index: false, follow: false },
};

export default function WelcomePage() {
  return <OnboardingFlow />;
}
