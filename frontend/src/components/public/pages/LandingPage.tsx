"use client";

import { LandingCta } from "@/components/public/landing/LandingCta";
import { LandingHero } from "@/components/public/landing/LandingHero";
import { LandingProblems } from "@/components/public/landing/LandingProblems";
import { LandingSecurity } from "@/components/public/landing/LandingSecurity";
import { LandingUseCases } from "@/components/public/landing/LandingUseCases";
import { LandingWorkflow } from "@/components/public/landing/LandingWorkflow";
import { resolvePublicSiteLinks } from "@/lib/public-site/links";

/**
 * Public landing page (minimal modern redesign). Uses the `site-*` design
 * tokens so it follows the light/dark preference set by the marketing layout.
 */
export function LandingPage() {
  const links = resolvePublicSiteLinks();

  return (
    <div className="bg-site-canvas text-site-ink">
      <LandingHero links={links} />
      <LandingProblems />
      <LandingWorkflow />
      <LandingUseCases />
      <LandingSecurity links={links} />
      <LandingCta links={links} />
    </div>
  );
}
