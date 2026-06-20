import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { ChangelogPage } from "@/components/public/pages/ChangelogPage";
import { buildPublicMetadata } from "@/lib/public-site/seo";

export const metadata = buildPublicMetadata({
  title: "Changelog | Rudix",
  description:
    "Browse public Rudix release notes, product improvements, fixes, and safe links to supporting documentation.",
  path: "/changelog",
});

export default function ChangelogRoutePage() {
  return (
    <PublicMarketingLayout pageLabel="Rudix changelog page">
      <ChangelogPage />
    </PublicMarketingLayout>
  );
}
