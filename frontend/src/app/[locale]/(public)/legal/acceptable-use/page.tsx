import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { AcceptableUsePolicyPage } from "@/components/public/pages/legal/AcceptableUsePolicyPage";
import { buildPublicMetadata } from "@/lib/public-site/seo";

export const metadata = buildPublicMetadata({
  title: "Acceptable Use Policy | Rudix",
  description:
    "Rudix Acceptable Use Policy covering permitted document indexing and query uses and prohibited activities including circumvention, abuse, and illegal content.",
  path: "/legal/acceptable-use",
});

export default function AcceptableUsePage() {
  return (
    <PublicMarketingLayout pageLabel="Rudix acceptable use policy">
      <AcceptableUsePolicyPage />
    </PublicMarketingLayout>
  );
}
