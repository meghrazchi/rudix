import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { InternalKnowledgeSolutionPage } from "@/components/public/pages/InternalKnowledgeSolutionPage";
import { buildLocalizedPublicMetadata } from "@/lib/public-site/seo";
import type { SupportedLocale } from "@/i18n/routing";

type PublicRouteParams = {
  params: Promise<{ locale: string }>;
};

export async function generateMetadata({ params }: PublicRouteParams) {
  const { locale } = await params;
  return buildLocalizedPublicMetadata({
    locale: locale as SupportedLocale,
    seoKey: "internalKnowledge",
    path: "/solutions/internal-knowledge",
  });
}

export default function InternalKnowledgeSolutionRoute() {
  return (
    <PublicMarketingLayout pageLabel="Internal Knowledge solution page">
      <InternalKnowledgeSolutionPage />
    </PublicMarketingLayout>
  );
}
