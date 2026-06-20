import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { AcceptableUsePolicyPage } from "@/components/public/pages/legal/AcceptableUsePolicyPage";
import { buildLocalizedPublicMetadata } from "@/lib/public-site/seo";
import type { SupportedLocale } from "@/i18n/routing";

type PublicRouteParams = {
  params: Promise<{ locale: string }>;
};

export async function generateMetadata({ params }: PublicRouteParams) {
  const { locale } = await params;
  return buildLocalizedPublicMetadata({
    locale: locale as SupportedLocale,
    seoKey: "acceptableUse",
    path: "/legal/acceptable-use",
  });
}

export default function AcceptableUsePage() {
  return (
    <PublicMarketingLayout pageLabel="Rudix acceptable use policy">
      <AcceptableUsePolicyPage />
    </PublicMarketingLayout>
  );
}
