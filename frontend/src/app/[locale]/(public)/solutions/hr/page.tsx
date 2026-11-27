import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { HRSolutionPage } from "@/components/public/pages/HRSolutionPage";
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
    seoKey: "hr",
    path: "/solutions/hr",
  });
}

export default function HRSolutionRoute({
  params,
}: Partial<PublicRouteParams>) {
  useRequestLocale(params);

  return (
    <PublicMarketingLayout pageLabel="HR solution page" theme="system">
      <HRSolutionPage />
    </PublicMarketingLayout>
  );
}
