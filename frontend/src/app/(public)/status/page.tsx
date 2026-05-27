import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { HeroSection } from "@/components/public/sections/PublicSections";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";
import { buildPublicMetadata } from "@/lib/public-site/seo";

export const metadata = buildPublicMetadata({
  title: "Status",
  description:
    "Public Rudix service status page destination and operational update entry point.",
  path: "/status",
  noIndex: true,
});

export default function StatusPage() {
  const links = resolvePublicSiteLinks();

  return (
    <PublicMarketingLayout pageLabel="Rudix status page">
      <HeroSection
        badge="Status"
        title="Service status destination"
        description="For live system-health details, use your configured status URL or contact support."
        actions={[
          { label: "Contact Support", href: links.contact, variant: "primary" },
          { label: "Back to Home", href: links.home, variant: "secondary" },
        ]}
      />
    </PublicMarketingLayout>
  );
}
