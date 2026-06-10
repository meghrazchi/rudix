import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { LegalSolutionPage } from "@/components/public/pages/LegalSolutionPage";
import { buildPublicMetadata } from "@/lib/public-site/seo";

export const metadata = buildPublicMetadata({
  title: "Legal Solution | Rudix",
  description:
    "Search contracts, legal policies, vendor agreements, renewal terms, and obligations with cited, source-backed answers. Enterprise RAG for legal and contract teams.",
  path: "/solutions/legal",
});

export default function LegalSolutionRoute() {
  return (
    <PublicMarketingLayout pageLabel="Legal solution page">
      <LegalSolutionPage />
    </PublicMarketingLayout>
  );
}
