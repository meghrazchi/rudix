import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { ComplianceSolutionPage } from "@/components/public/pages/ComplianceSolutionPage";
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
    seoKey: "compliance",
    path: "/solutions/compliance",
  });
}

export default function ComplianceSolutionRoute({
  params,
}: Partial<PublicRouteParams>) {
  useRequestLocale(params);

  return (
    <PublicMarketingLayout pageLabel="Compliance solution page" theme="system">
      <ComplianceSolutionPage />
    </PublicMarketingLayout>
  );
}
