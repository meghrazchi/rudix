import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { SecurityDisclosurePage } from "@/components/public/pages/legal/SecurityDisclosurePage";
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
    seoKey: "securityDisclosure",
    path: "/legal/security-disclosure",
  });
}

export default function SecurityDisclosureRoute({
  params,
}: Partial<PublicRouteParams>) {
  useRequestLocale(params);

  return (
    <PublicMarketingLayout
      pageLabel="Rudix security disclosure policy"
      theme="system"
    >
      <SecurityDisclosurePage />
    </PublicMarketingLayout>
  );
}
