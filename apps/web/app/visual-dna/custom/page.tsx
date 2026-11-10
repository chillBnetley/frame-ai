import { SiteHeader } from "@/components/site-header";
import { VisualDnaCustom } from "@/features/visual-dna/components/visual-dna-custom";

export const instant = false;

export default function VisualDnaCustomPage() {
  return (
    <div className="min-h-dvh">
      <SiteHeader />
      <VisualDnaCustom />
    </div>
  );
}
