import { render, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { SecurityTrustPage } from "@/components/public/pages/SecurityTrustPage";
import en from "@/i18n/messages/en.json";

vi.mock("@/components/public/PublicActionLink", () => ({
  PublicActionLink: ({
    href,
    children,
    className,
  }: {
    href: string;
    children: ReactNode;
    className?: string;
  }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}));

const security = en.public.security;

function renderSecurity() {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <SecurityTrustPage />
    </NextIntlClientProvider>,
  );
}

describe("SecurityTrustPage", () => {
  it("summarizes the security posture in the hero", () => {
    renderSecurity();

    const hero = screen
      .getByRole("heading", { level: 1 })
      .closest("section") as HTMLElement;
    for (const callout of [
      security.pillars.orgIsolationCallout,
      security.pillars.accessControlCallout,
      security.pillars.auditLogsCallout,
      security.pillars.encryptionCallout,
    ]) {
      expect(within(hero).getByText(callout)).toBeInTheDocument();
    }
  });

  it("renders all seven pillars and nine lifecycle steps in order", () => {
    renderSecurity();

    const pillars = screen.getByRole("region", { name: "Security pillars" });
    expect(within(pillars).getAllByRole("heading", { level: 3 })).toHaveLength(
      7,
    );

    const lifecycle = screen.getByRole("region", {
      name: "Document handling lifecycle",
    });
    const steps = within(lifecycle)
      .getAllByRole("heading", { level: 3 })
      .map((h) => h.textContent);
    expect(steps[0]).toBe("Validate");
    expect(steps.at(-1)).toBe("Re-index");
    expect(steps).toHaveLength(9);
  });

  it("keeps the no-certification-claim wording", () => {
    renderSecurity();

    expect(
      screen.getByText(security.compliance.readiness2),
    ).toBeInTheDocument();
  });

  it("points every security contact CTA at the security contact", () => {
    renderSecurity();

    const links = screen.getAllByRole("link", {
      name: /Talk to Security|Request Security Review/,
    });
    expect(links.length).toBeGreaterThanOrEqual(3);
    for (const link of links) {
      expect(link).toHaveAttribute("href", "/contact");
    }
  });
});
