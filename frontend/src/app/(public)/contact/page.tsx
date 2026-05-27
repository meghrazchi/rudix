import { PublicMarketingLayout } from "@/components/public/PublicMarketingLayout";
import {
  FinalCtaBand,
  HeroSection,
} from "@/components/public/sections/PublicSections";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";
import { buildPublicMetadata } from "@/lib/public-site/seo";

export const metadata = buildPublicMetadata({
  title: "Contact",
  description:
    "Contact Rudix to discuss product fit, security requirements, and enterprise deployment options.",
  path: "/contact",
});

export default function ContactPage() {
  const links = resolvePublicSiteLinks();

  return (
    <PublicMarketingLayout pageLabel="Rudix contact page">
      <HeroSection
        badge="Contact"
        title="Talk with the Rudix team"
        description="Tell us your document intelligence goals and we will help you map a secure rollout plan."
        actions={[
          {
            label: "Request Demo",
            href: links.requestDemo,
            variant: "primary",
          },
          { label: "Login", href: links.login, variant: "secondary" },
        ]}
      />

      <section
        className="mx-auto w-full max-w-4xl px-4 pb-16 lg:px-8"
        aria-labelledby="contact-options-title"
      >
        <h2
          id="contact-options-title"
          className="text-3xl font-black text-[#12141b]"
        >
          Contact options
        </h2>
        <div className="mt-6 grid gap-4 md:grid-cols-2">
          <article className="rounded-xl border border-[#d8dce7] bg-white p-5 shadow-sm">
            <h3 className="text-lg font-semibold text-[#171a24]">
              Sales and solution design
            </h3>
            <p className="mt-2 text-sm leading-7 text-[#5a6071]">
              Discuss architecture, security constraints, and production
              deployment plans.
            </p>
          </article>
          <article className="rounded-xl border border-[#d8dce7] bg-white p-5 shadow-sm">
            <h3 className="text-lg font-semibold text-[#171a24]">
              Support and onboarding
            </h3>
            <p className="mt-2 text-sm leading-7 text-[#5a6071]">
              Get help with setup, user access, and best-practice configuration.
            </p>
          </article>
        </div>
      </section>

      <FinalCtaBand
        title="Ready to see Rudix in action?"
        description="Schedule a guided walkthrough of ingestion, retrieval, evaluation, and governance flows."
        primaryLabel="Schedule Demo"
        primaryHref={links.requestDemo}
        secondaryLabel="View Product"
        secondaryHref={links.product}
      />
    </PublicMarketingLayout>
  );
}
