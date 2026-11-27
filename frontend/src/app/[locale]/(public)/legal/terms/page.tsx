import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { TermsOfServicePage } from "@/components/public/pages/legal/TermsOfServicePage";
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
    seoKey: "terms",
    path: "/legal/terms",
  });
}

export default function TermsPage({ params }: Partial<PublicRouteParams>) {
  useRequestLocale(params);

  return (
    <PublicMarketingLayout pageLabel="Rudix terms of service" theme="system">
      <TermsOfServicePage />
    </PublicMarketingLayout>
  );
}
