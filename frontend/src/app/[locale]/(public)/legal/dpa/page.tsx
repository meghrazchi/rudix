import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { DataProcessingAddendumPage } from "@/components/public/pages/legal/DataProcessingAddendumPage";
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
    seoKey: "dpa",
    path: "/legal/dpa",
  });
}

export default function DpaPage({ params }: Partial<PublicRouteParams>) {
  useRequestLocale(params);

  return (
    <PublicMarketingLayout
      pageLabel="Rudix data processing addendum"
      theme="system"
    >
      <DataProcessingAddendumPage />
    </PublicMarketingLayout>
  );
}
