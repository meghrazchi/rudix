import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { SubprocessorsPage } from "@/components/public/pages/legal/SubprocessorsPage";
import { buildPublicMetadata } from "@/lib/public-site/seo";

export const metadata = buildPublicMetadata({
  title: "Subprocessors | Rudix",
  description:
    "List of Rudix sub-processors including AI model providers, vector storage, object storage, and optional email and observability services.",
  path: "/legal/subprocessors",
});

export default function SubprocessorsRoute() {
  return (
    <PublicMarketingLayout pageLabel="Rudix subprocessors list">
      <SubprocessorsPage />
    </PublicMarketingLayout>
  );
}
