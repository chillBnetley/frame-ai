import { SiteHeader } from "@/components/site-header";
import { VisualDnaEvolve } from "@/features/visual-dna/components/visual-dna-evolve";

export const instant = false;

export default async function VisualDnaEvolvePage({
  params,
}: {
  params: Promise<{ styleId: string }>;
}) {
  const { styleId } = await params;
  return (
    <div className="min-h-dvh">
      <SiteHeader />
      <VisualDnaEvolve styleId={decodeURIComponent(styleId)} />
    </div>
  );
}
