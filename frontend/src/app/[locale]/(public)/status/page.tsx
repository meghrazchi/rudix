import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { StatusPage } from "@/components/public/pages/StatusPage";
import { getPublicStatusSnapshot } from "@/lib/api/public-status";
import { buildPublicMetadata } from "@/lib/public-site/seo";

export const dynamic = "force-dynamic";

export const metadata = buildPublicMetadata({
  title: "Status | Rudix",
  description:
    "View the public Rudix service status, active incidents, scheduled maintenance, and recent history.",
  path: "/status",
});

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
