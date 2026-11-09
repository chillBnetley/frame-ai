import { SiteHeader } from "@/components/site-header";
import { VisualDnaEditor } from "@/features/visual-dna/components/visual-dna-editor";

export const instant = false;

export default async function VisualDnaEditPage({
  params,
}: {
  params: Promise<{ styleId: string }>;
}) {
  const { styleId } = await params;
  return (
    <div className="min-h-dvh">
      <SiteHeader />
      <VisualDnaEditor styleId={decodeURIComponent(styleId)} />
    </div>
  );
}
