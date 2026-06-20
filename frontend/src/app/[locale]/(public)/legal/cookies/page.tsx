import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { CookiePolicyPage } from "@/components/public/pages/legal/CookiePolicyPage";
import { buildLocalizedPublicMetadata } from "@/lib/public-site/seo";
import type { SupportedLocale } from "@/i18n/routing";

type PublicRouteParams = {
  params: Promise<{ locale: string }>;
};

export async function generateMetadata({ params }: PublicRouteParams) {
  const { locale } = await params;
  return buildLocalizedPublicMetadata({
    locale: locale as SupportedLocale,
    seoKey: "cookies",
    path: "/legal/cookies",
  });
}

export default function CookiesPage() {
  return (
    <PublicMarketingLayout pageLabel="Rudix cookie policy">
      <CookiePolicyPage />
    </PublicMarketingLayout>
  );
}
