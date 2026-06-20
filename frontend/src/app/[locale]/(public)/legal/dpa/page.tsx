import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { DataProcessingAddendumPage } from "@/components/public/pages/legal/DataProcessingAddendumPage";
import { buildPublicMetadata } from "@/lib/public-site/seo";

export const metadata = buildPublicMetadata({
  title: "Data Processing Addendum | Rudix",
  description:
    "Rudix DPA covering processor obligations, sub-processors, data subject rights, security measures, and breach notification.",
  path: "/legal/dpa",
});

export default function DpaPage() {
  return (
    <PublicMarketingLayout pageLabel="Rudix data processing addendum">
      <DataProcessingAddendumPage />
    </PublicMarketingLayout>
  );
}
