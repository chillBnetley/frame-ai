import { SiteHeader } from "@/components/site-header";
import { StyleLibraryPage } from "@/features/master-vision/components/style-library-page";

export default function MasterStylesPage() {
  return (
    <div className="min-h-dvh">
      <SiteHeader />
      <StyleLibraryPage kind="master" />
    </div>
  );
}
