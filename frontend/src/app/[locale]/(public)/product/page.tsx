import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { ProductOverviewPage } from "@/components/public/pages/ProductOverviewPage";
import { buildPublicMetadata } from "@/lib/public-site/seo";

export const metadata = buildPublicMetadata({
  title: "Product Overview | Rudix",
  description:
    "See how Rudix turns documents into indexed, citation-backed answers with evaluations, pipeline visibility, and governance-ready operations.",
  path: "/product",
});

export default function ProductPage() {
  return (
    <PublicMarketingLayout pageLabel="Rudix product page">
      <ProductOverviewPage />
    </PublicMarketingLayout>
  );
}
