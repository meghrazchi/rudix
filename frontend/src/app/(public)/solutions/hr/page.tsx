import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { HRSolutionPage } from "@/components/public/pages/HRSolutionPage";
import { buildPublicMetadata } from "@/lib/public-site/seo";

export const metadata = buildPublicMetadata({
  title: "HR Solution | Rudix",
  description:
    "Help HR teams deliver consistent, citation-backed answers from handbooks, benefits guides, leave policies, and onboarding documents.",
  path: "/solutions/hr",
});

export default function HRSolutionRoute() {
  return (
    <PublicMarketingLayout pageLabel="HR solution page">
      <HRSolutionPage />
    </PublicMarketingLayout>
  );
}
