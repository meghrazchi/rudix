import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { LandingPage } from "@/components/public/pages/LandingPage";
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
    seoKey: "home",
    path: "/",
  });
}

export default function Home({ params }: Partial<PublicRouteParams>) {
  useRequestLocale(params);

  return (
    <PublicMarketingLayout pageLabel="Rudix public landing page" theme="system">
      <LandingPage />
    </PublicMarketingLayout>
  );
}
