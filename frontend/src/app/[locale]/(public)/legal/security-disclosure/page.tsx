import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { SecurityDisclosurePage } from "@/components/public/pages/legal/SecurityDisclosurePage";
import { buildPublicMetadata } from "@/lib/public-site/seo";

export const metadata = buildPublicMetadata({
  title: "Security Disclosure Policy | Rudix",
  description:
    "How to responsibly disclose security vulnerabilities in the Rudix platform, in-scope targets, response timelines, and researcher recognition.",
  path: "/legal/security-disclosure",
});

export default function SecurityDisclosureRoute() {
  return (
    <PublicMarketingLayout pageLabel="Rudix security disclosure policy">
      <SecurityDisclosurePage />
    </PublicMarketingLayout>
  );
}
