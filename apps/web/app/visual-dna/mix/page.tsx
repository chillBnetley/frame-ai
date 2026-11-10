import { SiteHeader } from "@/components/site-header";
import { VisualDnaMix } from "@/features/visual-dna/components/visual-dna-mix";

export const instant = false;

export default function VisualDnaMixPage() {
  return (
    <div className="min-h-dvh">
      <SiteHeader />
      <VisualDnaMix />
    </div>
  );
}