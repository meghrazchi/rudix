import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { SecurityTrustPage } from "@/components/public/pages/SecurityTrustPage";
import { buildPublicMetadata } from "@/lib/public-site/seo";

export const metadata = buildPublicMetadata({
  title: "Security & Trust | Rudix",
  description:
    "Learn how Rudix approaches document privacy, organization isolation, access controls, auditability, and secure AI document workflows.",
  path: "/security",
});

export default function SecurityPage() {
  return (
    <PublicMarketingLayout pageLabel="Rudix security page">
      <SecurityTrustPage />
    </PublicMarketingLayout>
  );
}
