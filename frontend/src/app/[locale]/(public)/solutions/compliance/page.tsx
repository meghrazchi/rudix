import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { ComplianceSolutionPage } from "@/components/public/pages/ComplianceSolutionPage";
import { buildLocalizedPublicMetadata } from "@/lib/public-site/seo";
import type { SupportedLocale } from "@/i18n/routing";

type PublicRouteParams = {
  params: Promise<{ locale: string }>;
};

export async function generateMetadata({ params }: PublicRouteParams) {
  const { locale } = await params;
  return buildLocalizedPublicMetadata({
    locale: locale as SupportedLocale,
    seoKey: "compliance",
    path: "/solutions/compliance",
  });
}

export default function ComplianceSolutionRoute() {
  return (
    <PublicMarketingLayout pageLabel="Compliance solution page">
      <ComplianceSolutionPage />
    </PublicMarketingLayout>
  );
}
