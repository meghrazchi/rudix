import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { ProductOverviewPage } from "@/components/public/pages/ProductOverviewPage";
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
    seoKey: "product",
    path: "/product",
  });
}

export default function ProductPage({ params }: Partial<PublicRouteParams>) {
  useRequestLocale(params);

  return (
    <PublicMarketingLayout pageLabel="Rudix product page" theme="system">
      <ProductOverviewPage />
    </PublicMarketingLayout>
  );
}
