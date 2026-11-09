import { SiteHeader } from "@/components/site-header";
import { VisualDnaCreate } from "@/features/visual-dna/components/visual-dna-create";

export const instant = false;

export default function VisualDnaNewPage() {
  return (
    <div className="min-h-dvh">
      <SiteHeader />
      <VisualDnaCreate />
    </div>
  );
}
