import { SiteHeader } from "@/components/site-header";
import { MasterVisionHome } from "@/features/master-vision/components/master-vision-home";

export default function MasterVisionPage() {
  return (
    <div className="min-h-dvh">
      <SiteHeader />
      <MasterVisionHome />
    </div>
  );
}
