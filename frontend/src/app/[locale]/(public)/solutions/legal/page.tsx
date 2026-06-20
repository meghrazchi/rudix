import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { LegalSolutionPage } from "@/components/public/pages/LegalSolutionPage";
import { buildLocalizedPublicMetadata } from "@/lib/public-site/seo";
import type { SupportedLocale } from "@/i18n/routing";

type PublicRouteParams = {
  params: Promise<{ locale: string }>;
};

export async function generateMetadata({ params }: PublicRouteParams) {
  const { locale } = await params;
  return buildLocalizedPublicMetadata({
    locale: locale as SupportedLocale,
    seoKey: "legal",
    path: "/solutions/legal",
  });
}

export default function LegalSolutionRoute() {
  return (
    <PublicMarketingLayout pageLabel="Legal solution page">
      <LegalSolutionPage />
    </PublicMarketingLayout>
  );
}
