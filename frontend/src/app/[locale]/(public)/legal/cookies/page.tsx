import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { CookiePolicyPage } from "@/components/public/pages/legal/CookiePolicyPage";
import { buildPublicMetadata } from "@/lib/public-site/seo";

export const metadata = buildPublicMetadata({
  title: "Cookie Policy | Rudix",
  description:
    "Rudix uses only essential session cookies and browser localStorage for preferences. No third-party tracking.",
  path: "/legal/cookies",
});

export default function CookiesPage() {
  return (
    <PublicMarketingLayout pageLabel="Rudix cookie policy">
      <CookiePolicyPage />
    </PublicMarketingLayout>
  );
}
