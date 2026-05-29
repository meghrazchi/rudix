import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { OperationsSolutionPage } from "@/components/public/pages/OperationsSolutionPage";
import { buildPublicMetadata } from "@/lib/public-site/seo";

export const metadata = buildPublicMetadata({
  title: "Operations Solution | Rudix",
  description:
    "Help operations, IT, DevOps, and SRE teams instantly retrieve incident steps, runbooks, SOPs, and troubleshooting procedures with cited, source-backed answers.",
  path: "/solutions/operations",
});

export default function OperationsSolutionRoute() {
  return (
    <PublicMarketingLayout pageLabel="Operations solution page">
      <OperationsSolutionPage />
    </PublicMarketingLayout>
  );
}
