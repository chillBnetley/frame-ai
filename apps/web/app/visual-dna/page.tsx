import { SiteHeader } from "@/components/site-header";
import { VisualDnaHome } from "@/features/visual-dna/components/visual-dna-home";

export default function VisualDnaPage() {
  return (
    <div className="min-h-dvh">
      <SiteHeader />
      <VisualDnaHome />
    </div>
  );
}
