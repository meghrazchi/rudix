import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { PrivacyPolicyPage } from "@/components/public/pages/legal/PrivacyPolicyPage";
import { buildLocalizedPublicMetadata } from "@/lib/public-site/seo";
import type { SupportedLocale } from "@/i18n/routing";

type PublicRouteParams = {
  params: Promise<{ locale: string }>;
};

export async function generateMetadata({ params }: PublicRouteParams) {
  const { locale } = await params;
  return buildLocalizedPublicMetadata({
    locale: locale as SupportedLocale,
    seoKey: "privacy",
    path: "/legal/privacy",
  });
}

export default function PrivacyPage() {
  return (
    <PublicMarketingLayout pageLabel="Rudix privacy policy">
      <PrivacyPolicyPage />
    </PublicMarketingLayout>
  );
}
