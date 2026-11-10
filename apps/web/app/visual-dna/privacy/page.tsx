import Link from "next/link";

import { SiteHeader } from "@/components/site-header";
import { PrivacyNotice } from "@/features/visual-dna/components/privacy-notice";
import { VisualDnaNav } from "@/features/visual-dna/components/visual-dna-nav";

export const instant = false;

export default function VisualDnaPrivacyPage() {
  return (
    <div className="min-h-dvh">
      <SiteHeader />
      <main className="mx-auto w-full max-w-[1080px] px-4 py-6 sm:px-6 lg:px-8">
        <VisualDnaNav />
        <div className="mt-6">
          <PrivacyNotice />
        </div>
        <div className="mt-4">
          <Link
            href="/visual-dna"
            className="text-xs font-medium text-[#277a68] hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            ← 返回我的风格
          </Link>
        </div>
      </main>
    </div>
  );
}
