import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { InternalKnowledgeSolutionPage } from "@/components/public/pages/InternalKnowledgeSolutionPage";
import { buildPublicMetadata } from "@/lib/public-site/seo";

export const metadata = buildPublicMetadata({
  title: "Internal Knowledge Solution | Rudix",
  description:
    "Turn scattered SOPs, handbooks, and playbooks into a trusted AI Q&A experience. Employees get citation-backed answers instantly with role-aware access control.",
  path: "/solutions/internal-knowledge",
});

export default function InternalKnowledgeSolutionRoute() {
  return (
    <PublicMarketingLayout pageLabel="Internal Knowledge solution page">
      <InternalKnowledgeSolutionPage />
    </PublicMarketingLayout>
  );
}
