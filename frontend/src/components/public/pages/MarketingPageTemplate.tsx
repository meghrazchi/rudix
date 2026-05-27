import {
  FeatureGridSection,
  type PublicFeatureItem,
  FaqSection,
  FinalCtaBand,
  HeroSection,
  WorkflowStripSection,
} from "@/components/public/sections/PublicSections";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

type MarketingPageTemplateProps = {
  heroBadge: string;
  heroTitle: string;
  heroDescription: string;
  featureTitle: string;
  featureDescription: string;
  features: PublicFeatureItem[];
  workflowTitle: string;
  workflowDescription: string;
  workflowSteps: Array<{ title: string; description: string }>;
  faqTitle: string;
  faqs: Array<{ question: string; answer: string }>;
};

export function MarketingPageTemplate({
  heroBadge,
  heroTitle,
  heroDescription,
  featureTitle,
  featureDescription,
  features,
  workflowTitle,
  workflowDescription,
  workflowSteps,
  faqTitle,
  faqs,
}: MarketingPageTemplateProps) {
  const links = resolvePublicSiteLinks();

  return (
    <>
      <HeroSection
        badge={heroBadge}
        title={heroTitle}
        description={heroDescription}
        actions={[
          {
            label: "Request Demo",
            href: links.requestDemo,
            variant: "primary",
          },
          { label: "Contact Sales", href: links.contact, variant: "secondary" },
        ]}
      />

      <FeatureGridSection
        title={featureTitle}
        description={featureDescription}
        items={features}
      />

      <WorkflowStripSection
        title={workflowTitle}
        description={workflowDescription}
        steps={workflowSteps}
      />

      <FaqSection title={faqTitle} items={faqs} />

      <FinalCtaBand
        title="Build with Rudix"
        description="Start with a secure RAG foundation and scale with confidence."
        primaryLabel="Get Started"
        primaryHref={links.startTrial}
        secondaryLabel="View Product"
        secondaryHref={links.product}
      />
    </>
  );
}
