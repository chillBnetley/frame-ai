import { SiteHeader } from "@/components/site-header";
import { StyleDetailView } from "@/features/master-vision/components/style-detail-view";

export const instant = false;

export default async function StyleDetailPage({
  params,
}: {
  params: Promise<{ styleId: string }>;
}) {
  const { styleId } = await params;
  return (
    <div className="min-h-dvh">
      <SiteHeader />
      <StyleDetailView styleId={decodeURIComponent(styleId)} />
    </div>
  );
}
