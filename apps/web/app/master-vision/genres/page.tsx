import { SiteHeader } from "@/components/site-header";
import { StyleLibraryPage } from "@/features/master-vision/components/style-library-page";

export default function MasterGenresPage() {
  return (
    <div className="min-h-dvh">
      <SiteHeader />
      <StyleLibraryPage kind="genre" />
    </div>
  );
}
