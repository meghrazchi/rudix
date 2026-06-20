import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { PrivacyPolicyPage } from "@/components/public/pages/legal/PrivacyPolicyPage";
import { buildPublicMetadata } from "@/lib/public-site/seo";

export const metadata = buildPublicMetadata({
  title: "Privacy Policy | Rudix",
  description:
    "Learn how Rudix collects, stores, and protects your data, including uploaded documents, AI queries, audit logs, and user accounts.",
  path: "/legal/privacy",
});

export default function PrivacyPage() {
  return (
    <PublicMarketingLayout pageLabel="Rudix privacy policy">
      <PrivacyPolicyPage />
    </PublicMarketingLayout>
  );
}
