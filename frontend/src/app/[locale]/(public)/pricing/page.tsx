import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { PricingOverviewPage } from "@/components/public/pages/PricingOverviewPage";
import { buildLocalizedPublicMetadata } from "@/lib/public-site/seo";
import type { SupportedLocale } from "@/i18n/routing";

type PublicRouteParams = {
  params: Promise<{ locale: string }>;
};

export async function generateMetadata({ params }: PublicRouteParams) {
  const { locale } = await params;
  return buildLocalizedPublicMetadata({
    locale: locale as SupportedLocale,
    seoKey: "pricing",
    path: "/pricing",
  });
}

export default function PricingPage() {
  return (
    <PublicMarketingLayout pageLabel="Rudix pricing page">
      <PricingOverviewPage />
    </PublicMarketingLayout>
  );
}
