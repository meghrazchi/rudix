import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { SolutionsOverviewPage } from "@/components/public/pages/SolutionsOverviewPage";
import { buildLocalizedPublicMetadata } from "@/lib/public-site/seo";
import type { SupportedLocale } from "@/i18n/routing";

type PublicRouteParams = {
  params: Promise<{ locale: string }>;
};

export async function generateMetadata({ params }: PublicRouteParams) {
  const { locale } = await params;
  return buildLocalizedPublicMetadata({
    locale: locale as SupportedLocale,
    seoKey: "solutions",
    path: "/solutions",
  });
}

export default function SolutionsPage() {
  return (
    <PublicMarketingLayout pageLabel="Rudix solutions overview page">
      <SolutionsOverviewPage />
    </PublicMarketingLayout>
  );
}
