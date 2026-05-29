import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { SupportSolutionPage } from "@/components/public/pages/SupportSolutionPage";
import { buildPublicMetadata } from "@/lib/public-site/seo";

export const metadata = buildPublicMetadata({
  title: "Support Solution | Rudix",
  description:
    "Help support teams resolve tickets faster with cited answers from approved help-center articles, troubleshooting guides, escalation playbooks, and SLA policies.",
  path: "/solutions/support",
});

export default function SupportSolutionRoute() {
  return (
    <PublicMarketingLayout pageLabel="Support solution page">
      <SupportSolutionPage />
    </PublicMarketingLayout>
  );
}
