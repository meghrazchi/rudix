import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { SalesSolutionPage } from "@/components/public/pages/SalesSolutionPage";
import { buildPublicMetadata } from "@/lib/public-site/seo";

export const metadata = buildPublicMetadata({
  title: "Sales Solution | Rudix",
  description:
    "Empower sales teams to answer deal questions instantly with cited answers from battlecards, RFP templates, pricing sheets, and product specs. Source-backed sales intelligence at speed.",
  path: "/solutions/sales",
});

export default function SalesSolutionRoute() {
  return (
    <PublicMarketingLayout pageLabel="Sales solution page">
      <SalesSolutionPage />
    </PublicMarketingLayout>
  );
}
