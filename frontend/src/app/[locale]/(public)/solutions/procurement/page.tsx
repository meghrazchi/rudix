import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { ProcurementSolutionPage } from "@/components/public/pages/ProcurementSolutionPage";
import { buildPublicMetadata } from "@/lib/public-site/seo";

export const metadata = buildPublicMetadata({
  title: "Procurement Solution | Rudix",
  description:
    "Accelerate vendor due diligence and procurement policy review with citation-backed answers from SOC2 reports, vendor contracts, RFP responses, and security questionnaires.",
  path: "/solutions/procurement",
});

export default function ProcurementSolutionRoute() {
  return (
    <PublicMarketingLayout pageLabel="Procurement solution page">
      <ProcurementSolutionPage />
    </PublicMarketingLayout>
  );
}
