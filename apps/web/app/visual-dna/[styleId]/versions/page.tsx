import { SiteHeader } from "@/components/site-header";
import { VisualDnaVersions } from "@/features/visual-dna/components/visual-dna-versions";

export const instant = false;

export default async function VisualDnaVersionsPage({
  params,
}: {
  params: Promise<{ styleId: string }>;
}) {
  const { styleId } = await params;
  return (
    <div className="min-h-dvh">
      <SiteHeader />
      <VisualDnaVersions styleId={decodeURIComponent(styleId)} />
    </div>
  );
}
