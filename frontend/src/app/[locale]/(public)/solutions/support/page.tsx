import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { SupportSolutionPage } from "@/components/public/pages/SupportSolutionPage";
import { buildLocalizedPublicMetadata } from "@/lib/public-site/seo";
import type { SupportedLocale } from "@/i18n/routing";

type PublicRouteParams = {
  params: Promise<{ locale: string }>;
};

export async function generateMetadata({ params }: PublicRouteParams) {
  const { locale } = await params;
  return buildLocalizedPublicMetadata({
    locale: locale as SupportedLocale,
    seoKey: "support",
    path: "/solutions/support",
  });
}

export default function SupportSolutionRoute() {
  return (
    <PublicMarketingLayout pageLabel="Support solution page">
      <SupportSolutionPage />
    </PublicMarketingLayout>
  );
}
