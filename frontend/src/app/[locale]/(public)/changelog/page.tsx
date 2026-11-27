import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { ChangelogPage } from "@/components/public/pages/ChangelogPage";
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
    seoKey: "changelog",
    path: "/changelog",
  });
}

export default function ChangelogRoutePage({
  params,
}: Partial<PublicRouteParams>) {
  useRequestLocale(params);

  return (
    <PublicMarketingLayout pageLabel="Rudix changelog page" theme="system">
      <ChangelogPage />
    </PublicMarketingLayout>
  );
}
