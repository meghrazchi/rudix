import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { ContactDemoPage } from "@/components/public/pages/ContactDemoPage";
import { buildLocalizedPublicMetadata } from "@/lib/public-site/seo";
import type { SupportedLocale } from "@/i18n/routing";

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

export default function ContactPage() {
  return (
    <PublicMarketingLayout pageLabel="Rudix contact page">
      <ContactDemoPage />
    </PublicMarketingLayout>
  );
}
