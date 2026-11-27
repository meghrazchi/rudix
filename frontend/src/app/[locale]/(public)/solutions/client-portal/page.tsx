import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { ClientPortalSolutionPage } from "@/components/public/pages/ClientPortalSolutionPage";
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
    seoKey: "clientPortal",
    path: "/solutions/client-portal",
  });
}

export default function ClientPortalSolutionRoute({
  params,
}: Partial<PublicRouteParams>) {
  useRequestLocale(params);

  return (
    <PublicMarketingLayout
      pageLabel="Client Portal solution page"
      theme="system"
    >
      <ClientPortalSolutionPage />
    </PublicMarketingLayout>
  );
}
