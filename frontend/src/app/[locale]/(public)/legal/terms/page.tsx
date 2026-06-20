import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { TermsOfServicePage } from "@/components/public/pages/legal/TermsOfServicePage";
import { buildPublicMetadata } from "@/lib/public-site/seo";

export const metadata = buildPublicMetadata({
  title: "Terms of Service | Rudix",
  description:
    "Read the Rudix Terms of Service covering permitted use, restrictions, content ownership, service availability, and liability.",
  path: "/legal/terms",
});

export default function TermsPage() {
  return (
    <PublicMarketingLayout pageLabel="Rudix terms of service">
      <TermsOfServicePage />
    </PublicMarketingLayout>
  );
}
