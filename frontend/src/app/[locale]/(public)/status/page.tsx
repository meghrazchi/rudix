import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { StatusPage } from "@/components/public/pages/StatusPage";
import { getPublicStatusSnapshot } from "@/lib/api/public-status";
import { buildLocalizedPublicMetadata } from "@/lib/public-site/seo";
import type { SupportedLocale } from "@/i18n/routing";

type PublicRouteParams = {
  params: Promise<{ locale: string }>;
};

export const dynamic = "force-dynamic";

export async function generateMetadata({ params }: PublicRouteParams) {
  const { locale } = await params;
  return buildLocalizedPublicMetadata({
    locale: locale as SupportedLocale,
    seoKey: "status",
    path: "/status",
  });
}

export default async function StatusRoute() {
  let snapshot = null;
  let loadError: string | null = null;

  try {
    snapshot = await getPublicStatusSnapshot();
  } catch {
    loadError = "Unable to load live status data.";
  }

  return (
    <PublicMarketingLayout pageLabel="Rudix status page">
      <StatusPage snapshot={snapshot} loadError={loadError} />
    </PublicMarketingLayout>
  );
}
