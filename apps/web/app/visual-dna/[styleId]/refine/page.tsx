import { SiteHeader } from "@/components/site-header";
import { VisualDnaRefine } from "@/features/visual-dna/components/visual-dna-refine";

export const instant = false;

export default async function VisualDnaRefinePage({
  params,
}: {
  params: Promise<{ styleId: string }>;
}) {
  const { styleId } = await params;
  return (
    <div className="min-h-dvh">
      <SiteHeader />
      <VisualDnaRefine styleId={decodeURIComponent(styleId)} />
    </div>
  );
}
