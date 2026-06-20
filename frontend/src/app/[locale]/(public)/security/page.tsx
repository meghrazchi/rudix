import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { SecurityTrustPage } from "@/components/public/pages/SecurityTrustPage";
import { buildLocalizedPublicMetadata } from "@/lib/public-site/seo";
import type { SupportedLocale } from "@/i18n/routing";

type PublicRouteParams = {
  params: Promise<{ locale: string }>;
};

export async function generateMetadata({ params }: PublicRouteParams) {
  const { locale } = await params;
  return buildLocalizedPublicMetadata({
    locale: locale as SupportedLocale,
    seoKey: "security",
    path: "/security",
  });
}

export default function SecurityPage() {
  return (
    <PublicMarketingLayout pageLabel="Rudix security page">
      <SecurityTrustPage />
    </PublicMarketingLayout>
  );
}
