import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { SolutionsOverviewPage } from "@/components/public/pages/SolutionsOverviewPage";
import { buildLocalizedPublicMetadata } from "@/lib/public-site/seo";
import type { SupportedLocale } from "@/i18n/routing";
import { useRequestLocale } from "@/i18n/request-locale";

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

export default function SolutionsPage({ params }: Partial<PublicRouteParams>) {
  useRequestLocale(params);

  return (
    <PublicMarketingLayout
      pageLabel="Rudix solutions overview page"
      theme="system"
    >
      <SolutionsOverviewPage />
    </PublicMarketingLayout>
  );
}
