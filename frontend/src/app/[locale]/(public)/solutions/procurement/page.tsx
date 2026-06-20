import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { ProcurementSolutionPage } from "@/components/public/pages/ProcurementSolutionPage";
import { buildLocalizedPublicMetadata } from "@/lib/public-site/seo";
import type { SupportedLocale } from "@/i18n/routing";

type PublicRouteParams = {
  params: Promise<{ locale: string }>;
};

export async function generateMetadata({ params }: PublicRouteParams) {
  const { locale } = await params;
  return buildLocalizedPublicMetadata({
    locale: locale as SupportedLocale,
    seoKey: "procurement",
    path: "/solutions/procurement",
  });
}

export default function ProcurementSolutionRoute() {
  return (
    <PublicMarketingLayout pageLabel="Procurement solution page">
      <ProcurementSolutionPage />
    </PublicMarketingLayout>
  );
}
