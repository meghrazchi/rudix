import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { MarketingPageTemplate } from "@/components/public/pages/MarketingPageTemplate";
import type { PublicFeatureItem } from "@/components/public/sections/PublicSections";
import { buildPublicMetadata } from "@/lib/public-site/seo";

const features: PublicFeatureItem[] = [
  {
    icon: "pipeline",
    title: "Pipeline Explorer",
    description:
      "Visualize each ingestion and answer step with run-level context.",
  },
  {
    icon: "evaluation",
    title: "Grounded Chat",
    description:
      "Deliver cited answers with confidence and not-found safeguards.",
  },
  {
    icon: "governance",
    title: "Operational Controls",
    description:
      "Apply organization policies, budgets, and access boundaries across teams.",
  },
];

export const metadata = buildPublicMetadata({
  title: "Product",
  description:
    "Explore Rudix product capabilities for secure ingestion, grounded generation, and operational observability.",
  path: "/product",
});

export default function ProductPage() {
  return (
    <PublicMarketingLayout pageLabel="Rudix product page">
      <MarketingPageTemplate
        heroBadge="Product"
        heroTitle="Enterprise RAG platform for production teams"
        heroDescription="Rudix combines secure ingestion, traceable retrieval, and grounded generation in one cohesive platform."
        featureTitle="What You Can Build"
        featureDescription="Ship reliable document intelligence experiences with platform-level controls."
        features={features}
        workflowTitle="From Documents to Trusted Answers"
        workflowDescription="Use a consistent architecture that scales from pilot to production without rewriting core workflows."
        workflowSteps={[
          {
            title: "Connect",
            description:
              "Ingest PDFs, DOCX, and text from approved internal sources.",
          },
          {
            title: "Process",
            description:
              "Chunk, embed, and index data with policy-aware metadata.",
          },
          {
            title: "Query",
            description:
              "Retrieve, rerank, and generate answers grounded in citations.",
          },
          {
            title: "Observe",
            description:
              "Monitor confidence, latency, and failure trends over time.",
          },
        ]}
        faqTitle="Product FAQ"
        faqs={[
          {
            question: "Does Rudix support multi-tenant isolation?",
            answer:
              "Yes. Organization-level access controls are enforced across ingestion, retrieval, and answers.",
          },
          {
            question: "Can we start with one team before rolling out broadly?",
            answer:
              "Yes. You can launch with one workspace and scale governance controls as adoption grows.",
          },
        ]}
      />
    </PublicMarketingLayout>
  );
}
