import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { ContactDemoPage } from "@/components/public/pages/ContactDemoPage";
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
    seoKey: "contact",
    path: "/contact",
  });
}

export default function ContactPage({ params }: Partial<PublicRouteParams>) {
  useRequestLocale(params);

  return (
    <PublicMarketingLayout pageLabel="Rudix contact page" theme="system">
      <ContactDemoPage />
    </PublicMarketingLayout>
  );
}
