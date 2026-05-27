import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { MarketingPageTemplate } from "@/components/public/pages/MarketingPageTemplate";
import type { PublicFeatureItem } from "@/components/public/sections/PublicSections";
import { buildPublicMetadata } from "@/lib/public-site/seo";

const features: PublicFeatureItem[] = [
  {
    icon: "speed",
    title: "Usage Visibility",
    description:
      "Track questions, token usage, cost estimates, and latency trends for governance.",
  },
  {
    icon: "evaluation",
    title: "Quality Metrics",
    description:
      "Measure retrieval and answer quality with evaluation sets and run summaries.",
  },
  {
    icon: "governance",
    title: "Budget Controls",
    description:
      "Configure policy and budget limits for agentic and MCP-capable workflows.",
  },
];

export const metadata = buildPublicMetadata({
  title: "Pricing",
  description:
    "Understand Rudix pricing model foundations with usage visibility, quality metrics, and governance controls.",
  path: "/pricing",
});

export default function PricingPage() {
  return (
    <PublicMarketingLayout pageLabel="Rudix pricing page">
      <MarketingPageTemplate
        heroBadge="Pricing"
        heroTitle="Predictable platform economics"
        heroDescription="Align RAG usage growth with clear visibility into tokens, latency, and quality outcomes."
        featureTitle="Pricing Foundations"
        featureDescription="Model total cost of ownership with operational confidence and policy controls."
        features={features}
        workflowTitle="Measure before you scale"
        workflowDescription="Use shared metrics and policy controls to keep AI workloads cost-aware."
        workflowSteps={[
          {
            title: "Track",
            description:
              "Monitor requests, tokens, and latency in admin analytics.",
          },
          {
            title: "Evaluate",
            description: "Run quality evaluations before expanding use cases.",
          },
          {
            title: "Optimize",
            description:
              "Tune retrieval and reranking to improve cost-quality balance.",
          },
          {
            title: "Govern",
            description:
              "Set budgets and access controls for teams and environments.",
          },
        ]}
        faqTitle="Pricing FAQ"
        faqs={[
          {
            question: "Does Rudix expose usage telemetry for chargeback?",
            answer:
              "Yes. Usage summaries include key metrics that support internal cost allocation workflows.",
          },
          {
            question: "Can we control budgets for agent workflows?",
            answer:
              "Yes. Governance policy supports configurable step, call, and runtime budget constraints.",
          },
        ]}
      />
    </PublicMarketingLayout>
  );
}
