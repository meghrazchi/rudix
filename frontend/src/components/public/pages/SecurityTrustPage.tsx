import {
  FaqSection,
  FinalCtaBand,
} from "@/components/public/sections/PublicSections";
import {
  AccessGovernanceSection,
  ComplianceAndRetentionSection,
  DocumentHandlingSection,
  SecurityHeroSection,
  SecurityPillarsSection,
} from "@/components/public/pages/security/SecurityTrustSections";
import { securityFaqs } from "@/components/public/pages/security/securityData";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

export function SecurityTrustPage() {
  const links = resolvePublicSiteLinks();

  return (
    <>
      <SecurityHeroSection
        securityReviewHref={links.securityContact}
        architectureHref={links.docs}
      />
      <SecurityPillarsSection />
      <DocumentHandlingSection />
      <AccessGovernanceSection />
      <ComplianceAndRetentionSection
        securityContactHref={links.securityContact}
      />

      <FaqSection title="Security FAQ" items={securityFaqs} />

      <FinalCtaBand
        title="Request a security review"
        description="Discuss deployment boundaries, data-handling expectations, and governance requirements with the Rudix team."
        primaryLabel="Talk to Security"
        primaryHref={links.securityContact}
        secondaryLabel="Request Demo"
        secondaryHref={links.requestDemo}
      />
    </>
  );
}
