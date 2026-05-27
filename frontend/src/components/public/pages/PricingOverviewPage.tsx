import {
  FinalCtaBand,
  FaqSection,
} from "@/components/public/sections/PublicSections";
import {
  PlanComparisonSection,
  PricingHeroSection,
  PricingPlanCardsSection,
  UsageLimitsSection,
} from "@/components/public/pages/pricing/PricingSections";
import { pricingFaqs } from "@/components/public/pages/pricing/pricingData";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

export function PricingOverviewPage() {
  const links = resolvePublicSiteLinks();

  return (
    <>
      <PricingHeroSection links={links} />
      <PricingPlanCardsSection links={links} />
      <UsageLimitsSection />
      <PlanComparisonSection />

      <FaqSection title="Pricing FAQ" items={pricingFaqs} />

      <FinalCtaBand
        title="Need a tailored plan?"
        description="Talk with the Rudix team to align usage limits, deployment posture, and support coverage with your rollout."
        primaryLabel="Contact Sales"
        primaryHref={links.contact}
        secondaryLabel="Request Demo"
        secondaryHref={links.requestDemo}
      />
    </>
  );
}
