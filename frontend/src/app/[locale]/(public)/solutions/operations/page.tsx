import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { OperationsSolutionPage } from "@/components/public/pages/OperationsSolutionPage";
import { buildLocalizedPublicMetadata } from "@/lib/public-site/seo";
import type { SupportedLocale } from "@/i18n/routing";

type PublicRouteParams = {
  params: Promise<{ locale: string }>;
};

export async function generateMetadata({ params }: PublicRouteParams) {
  const { locale } = await params;
  return buildLocalizedPublicMetadata({
    locale: locale as SupportedLocale,
    seoKey: "operations",
    path: "/solutions/operations",
  });
}

export default function OperationsSolutionRoute() {
  return (
    <PublicMarketingLayout pageLabel="Operations solution page">
      <OperationsSolutionPage />
    </PublicMarketingLayout>
  );
}
