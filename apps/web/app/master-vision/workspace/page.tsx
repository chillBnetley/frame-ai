import { SiteHeader } from "@/components/site-header";
import { MasterVisionWorkspace } from "@/features/master-vision/components/workspace/master-vision-workspace";

export const instant = false;

export default async function WorkspacePage({
  searchParams,
}: {
  searchParams: Promise<{ style?: string | string[]; session?: string | string[] }>;
}) {
  const params = await searchParams;
  const style = Array.isArray(params.style) ? params.style[0] : params.style;
  const session = Array.isArray(params.session) ? params.session[0] : params.session;
  return (
    <div className="min-h-dvh">
      <SiteHeader />
      <MasterVisionWorkspace
        initialStyleId={style ?? ""}
        initialSessionId={session ?? ""}
      />
    </div>
  );
}
