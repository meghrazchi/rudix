import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { ResearchSolutionPage } from "@/components/public/pages/ResearchSolutionPage";
import { buildLocalizedPublicMetadata } from "@/lib/public-site/seo";
import type { SupportedLocale } from "@/i18n/routing";

type PublicRouteParams = {
  params: Promise<{ locale: string }>;
};

export async function generateMetadata({ params }: PublicRouteParams) {
  const { locale } = await params;
  return buildLocalizedPublicMetadata({
    locale: locale as SupportedLocale,
    seoKey: "research",
    path: "/solutions/research",
  });
}

export default function ResearchSolutionRoute() {
  return (
    <PublicMarketingLayout pageLabel="Research solution page">
      <ResearchSolutionPage />
    </PublicMarketingLayout>
  );
}
