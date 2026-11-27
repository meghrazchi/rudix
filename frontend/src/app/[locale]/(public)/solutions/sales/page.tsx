import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { SalesSolutionPage } from "@/components/public/pages/SalesSolutionPage";
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
    seoKey: "sales",
    path: "/solutions/sales",
  });
}

export default function SalesSolutionRoute({
  params,
}: Partial<PublicRouteParams>) {
  useRequestLocale(params);

  return (
    <PublicMarketingLayout pageLabel="Sales solution page" theme="system">
      <SalesSolutionPage />
    </PublicMarketingLayout>
  );
}
