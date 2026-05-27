import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import { MarketingPageTemplate } from "@/components/public/pages/MarketingPageTemplate";
import type { PublicFeatureItem } from "@/components/public/sections/PublicSections";
import { buildPublicMetadata } from "@/lib/public-site/seo";

const features: PublicFeatureItem[] = [
  {
    icon: "security",
    title: "Encryption by Default",
    description:
      "Protect data in transit and at rest across document and retrieval workflows.",
  },
  {
    icon: "governance",
    title: "Tenant Isolation",
    description:
      "Enforce organization-scoped retrieval and policy boundaries across surfaces.",
  },
  {
    icon: "pipeline",
    title: "Operational Auditability",
    description:
      "Track document lifecycle, answer traces, and administrative actions safely.",
  },
];

export const metadata = buildPublicMetadata({
  title: "Security",
  description:
    "Review Rudix security posture, tenant isolation controls, and operational governance safeguards.",
  path: "/security",
});

export default function SecurityPage() {
  return (
    <PublicMarketingLayout pageLabel="Rudix security page">
      <MarketingPageTemplate
        heroBadge="Security"
        heroTitle="Security-first by architecture"
        heroDescription="Rudix is designed for enterprise governance, least privilege, and resilient production operations."
        featureTitle="Security Controls"
        featureDescription="Build AI document workflows on a hardened and auditable foundation."
        features={features}
        workflowTitle="Secure by default"
        workflowDescription="Controls are embedded in ingestion, retrieval, generation, and admin workflows."
        workflowSteps={[
          {
            title: "Authenticate",
            description:
              "Validate user identity and role before tool or API execution.",
          },
          {
            title: "Authorize",
            description:
              "Enforce organization isolation and role-based access per resource.",
          },
          {
            title: "Observe",
            description:
              "Capture safe request IDs and structured operational signals.",
          },
          {
            title: "Review",
            description:
              "Audit policy updates, approvals, and runtime decisions.",
          },
        ]}
        faqTitle="Security FAQ"
        faqs={[
          {
            question: "Is sensitive document text logged by default?",
            answer:
              "No. Rudix emphasizes safe logging and avoids exposing protected raw content by default.",
          },
          {
            question: "Can we keep deployment inside our own infrastructure?",
            answer:
              "Yes. Rudix supports private deployment and controlled environment-specific configuration.",
          },
        ]}
      />
    </PublicMarketingLayout>
  );
}
