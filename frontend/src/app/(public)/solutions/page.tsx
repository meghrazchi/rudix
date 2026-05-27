import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { MarketingPageTemplate } from "@/components/public/pages/MarketingPageTemplate";
import type { PublicFeatureItem } from "@/components/public/sections/PublicSections";
import { buildPublicMetadata } from "@/lib/public-site/seo";

const features: PublicFeatureItem[] = [
  {
    icon: "ingestion",
    title: "Policy-Aware Ingestion",
    description:
      "Bring internal documents into a governed retrieval pipeline with auditable processing.",
  },
  {
    icon: "pipeline",
    title: "Traceable Operations",
    description:
      "Inspect how each result was produced across indexing, retrieval, and generation.",
  },
  {
    icon: "speed",
    title: "Low-Latency Responses",
    description:
      "Tune top-k and reranking behavior for performance and answer quality targets.",
  },
];

export const metadata = buildPublicMetadata({
  title: "Solutions",
  description:
    "See how Rudix supports enterprise teams with secure document intelligence and grounded AI answer workflows.",
  path: "/solutions",
});

export default function SolutionsPage() {
  return (
    <PublicMarketingLayout pageLabel="Rudix solutions page">
      <MarketingPageTemplate
        heroBadge="Solutions"
        heroTitle="Document intelligence for enterprise use cases"
        heroDescription="Rudix helps teams build secure retrieval and answer workflows for internal knowledge at scale."
        featureTitle="Core Solution Areas"
        featureDescription="Align retrieval quality, compliance posture, and developer velocity from one platform."
        features={features}
        workflowTitle="Standardized RAG delivery"
        workflowDescription="Move from fragmented experiments to a repeatable enterprise architecture."
        workflowSteps={[
          {
            title: "Scope",
            description:
              "Define document access by organization, role, and content policy.",
          },
          {
            title: "Index",
            description:
              "Create retrieval-ready chunks and vectors with metadata filters.",
          },
          {
            title: "Assist",
            description:
              "Deliver cited answers with confidence and not-found safeguards.",
          },
          {
            title: "Improve",
            description: "Use evaluation runs to improve quality over time.",
          },
        ]}
        faqTitle="Solutions FAQ"
        faqs={[
          {
            question: "Can Rudix limit chat to selected indexed documents?",
            answer:
              "Yes. Users can scope questions to one or more indexed documents through retrieval settings.",
          },
          {
            question: "Does Rudix provide evaluation metrics?",
            answer:
              "Yes. Run-level and question-level metrics are available for quality monitoring and tuning.",
          },
        ]}
      />
    </PublicMarketingLayout>
  );
}
