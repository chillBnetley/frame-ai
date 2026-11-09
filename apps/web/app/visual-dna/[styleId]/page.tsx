import { SiteHeader } from "@/components/site-header";
import { VisualDnaDetail } from "@/features/visual-dna/components/visual-dna-detail";

export const instant = false;

export default async function VisualDnaDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ styleId: string }>;
  searchParams: Promise<{ start?: string | string[] }>;
}) {
  const { styleId } = await params;
  const query = await searchParams;
  const start = Array.isArray(query.start) ? query.start[0] : query.start;
  return (
    <div className="min-h-dvh">
      <SiteHeader />
      <VisualDnaDetail
        styleId={decodeURIComponent(styleId)}
        autoStart={start === "1"}
      />
    </div>
  );
}
