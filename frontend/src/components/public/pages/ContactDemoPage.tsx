import {
  ContactHeroSection,
  ContactMainSection,
  ContactMapSection,
} from "@/components/public/pages/contact/ContactDemoSections";
import {
  FinalCtaBand,
  FaqSection,
} from "@/components/public/sections/PublicSections";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";
import { resolveContactSubmissionConfig } from "@/lib/public-site/contact";

const CONTACT_FAQS = [
  {
    question: "Can we request a demo before finalizing packaging?",
    answer:
      "Yes. The Rudix team can run a guided demo aligned to your document workflow and rollout goals.",
  },
  {
    question: "Do you support security review requests?",
    answer:
      "Yes. You can route security review questions through this page and coordinate next steps with the team.",
  },
  {
    question:
      "Can we use a scheduling link instead of a direct API submission?",
    answer:
      "Yes. When configured, the contact flow can route to a scheduling or CRM destination.",
  },
  {
    question: "What happens if contact submission is not configured?",
    answer:
      "The page provides fallback contact options so visitors can still reach sales, support, and security contacts.",
  },
];

export function ContactDemoPage() {
  const links = resolvePublicSiteLinks();
  const submissionConfig = resolveContactSubmissionConfig(links);

  return (
    <>
      <ContactHeroSection />
      <ContactMainSection links={links} submissionConfig={submissionConfig} />
      <ContactMapSection />

      <FaqSection title="Contact and demo FAQ" items={CONTACT_FAQS} />

      <FinalCtaBand
        title="Need a live walkthrough?"
        description="Schedule a demo with Rudix to review your use case, success criteria, and rollout path."
        primaryLabel="Request Demo"
        primaryHref={links.requestDemo}
        secondaryLabel="View Product"
        secondaryHref={links.product}
      />
    </>
  );
}
