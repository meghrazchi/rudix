import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { SubprocessorsPage } from "@/components/public/pages/legal/SubprocessorsPage";
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
    seoKey: "subprocessors",
    path: "/legal/subprocessors",
  });
}

export default function SubprocessorsRoute({
  params,
}: Partial<PublicRouteParams>) {
  useRequestLocale(params);

  return (
    <PublicMarketingLayout pageLabel="Rudix subprocessors list" theme="system">
      <SubprocessorsPage />
    </PublicMarketingLayout>
  );
}
