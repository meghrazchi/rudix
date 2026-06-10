import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { ResearchSolutionPage } from "@/components/public/pages/ResearchSolutionPage";
import { buildPublicMetadata } from "@/lib/public-site/seo";

export const metadata = buildPublicMetadata({
  title: "Research Solution | Rudix",
  description:
    "Transform research corpora into traceable intelligence. Query market reports, analyst papers, technical docs, and internal memos with cited, source-grounded answers.",
  path: "/solutions/research",
});

export default function ResearchSolutionRoute() {
  return (
    <PublicMarketingLayout pageLabel="Research solution page">
      <ResearchSolutionPage />
    </PublicMarketingLayout>
  );
}
