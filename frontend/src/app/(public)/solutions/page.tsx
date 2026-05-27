import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { SolutionsOverviewPage } from "@/components/public/pages/SolutionsOverviewPage";
import { buildPublicMetadata } from "@/lib/public-site/seo";

export const metadata = buildPublicMetadata({
  title: "Solutions Overview | Rudix",
  description:
    "Discover department-focused Rudix solutions for HR, Support, Legal, Compliance, Operations, and Research teams.",
  path: "/solutions",
});

export default function SolutionsPage() {
  return (
    <PublicMarketingLayout pageLabel="Rudix solutions overview page">
      <SolutionsOverviewPage />
    </PublicMarketingLayout>
  );
}
