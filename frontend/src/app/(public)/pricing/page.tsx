import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { PricingOverviewPage } from "@/components/public/pages/PricingOverviewPage";
import { buildPublicMetadata } from "@/lib/public-site/seo";

export const metadata = buildPublicMetadata({
  title: "Pricing | Rudix",
  description:
    "Compare Rudix plans for document AI, RAG chat, evaluations, and governance with configurable packaging guidance.",
  path: "/pricing",
});

export default function PricingPage() {
  return (
    <PublicMarketingLayout pageLabel="Rudix pricing page">
      <PricingOverviewPage />
    </PublicMarketingLayout>
  );
}
