import { SiteHeader } from "@/components/site-header";
import { MasterVisionWorkspace } from "@/features/master-vision/components/workspace/master-vision-workspace";

export const instant = false;

export default async function WorkspacePage({
  searchParams,
}: {
  searchParams: Promise<{ style?: string | string[] }>;
}) {
  const params = await searchParams;
  const style = Array.isArray(params.style) ? params.style[0] : params.style;
  return (
    <div className="min-h-dvh">
      <SiteHeader />
      <MasterVisionWorkspace initialStyleId={style ?? ""} />
    </div>
  );
}
