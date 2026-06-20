import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { LandingPage } from "@/components/public/pages/LandingPage";
import { buildLocalizedPublicMetadata } from "@/lib/public-site/seo";
import type { SupportedLocale } from "@/i18n/routing";

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

export default function Home() {
  return (
    <PublicMarketingLayout pageLabel="Rudix public landing page">
      <LandingPage />
    </PublicMarketingLayout>
  );
}
