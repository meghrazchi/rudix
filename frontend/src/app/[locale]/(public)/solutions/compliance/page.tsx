import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { ComplianceSolutionPage } from "@/components/public/pages/ComplianceSolutionPage";
import { buildPublicMetadata } from "@/lib/public-site/seo";

export const metadata = buildPublicMetadata({
  title: "Compliance Solution | Rudix",
  description:
    "Retrieve cited answers from policies, audit evidence, security controls, and compliance files. Accelerate audit readiness with traceable, governance-ready knowledge retrieval.",
  path: "/solutions/compliance",
});

export default function ComplianceSolutionRoute() {
  return (
    <PublicMarketingLayout pageLabel="Compliance solution page">
      <ComplianceSolutionPage />
    </PublicMarketingLayout>
  );
}
