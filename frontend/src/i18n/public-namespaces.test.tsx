import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ComponentType, ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import enMessages from "./messages/en.json";
import { pickMessages } from "./messages";
import { APP_NAMESPACES, PUBLIC_NAMESPACES } from "./namespaces";

// src/test/setup.ts stubs next-intl with the full English catalogue. Here the
// real provider runs with only PUBLIC_NAMESPACES, as app/[locale]/layout.tsx
// ships them, and any missing message throws (R07-02).
vi.mock("next-intl", async (importOriginal) => importOriginal());

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: { status: "unauthenticated", session: null },
    setAuthenticatedSession: vi.fn(),
    clearBoundaryEvent: vi.fn(),
    signOut: vi.fn(),
  }),
}));

import Home from "@/app/[locale]/(public)/page";
import ProductPage from "@/app/[locale]/(public)/product/page";
import PricingPage from "@/app/[locale]/(public)/pricing/page";
import SecurityPage from "@/app/[locale]/(public)/security/page";
import SolutionsPage from "@/app/[locale]/(public)/solutions/page";
import ClientPortalRoute from "@/app/[locale]/(public)/solutions/client-portal/page";
import ComplianceRoute from "@/app/[locale]/(public)/solutions/compliance/page";
import HRRoute from "@/app/[locale]/(public)/solutions/hr/page";
import InternalKnowledgeRoute from "@/app/[locale]/(public)/solutions/internal-knowledge/page";
import LegalSolutionRoute from "@/app/[locale]/(public)/solutions/legal/page";
import OperationsRoute from "@/app/[locale]/(public)/solutions/operations/page";
import ProcurementRoute from "@/app/[locale]/(public)/solutions/procurement/page";
import ResearchRoute from "@/app/[locale]/(public)/solutions/research/page";
import SalesRoute from "@/app/[locale]/(public)/solutions/sales/page";
import SupportRoute from "@/app/[locale]/(public)/solutions/support/page";
import ContactPage from "@/app/[locale]/(public)/contact/page";
import ChangelogPage from "@/app/[locale]/(public)/changelog/page";
import AcceptableUsePage from "@/app/[locale]/(public)/legal/acceptable-use/page";
import CookiesPage from "@/app/[locale]/(public)/legal/cookies/page";
import DpaPage from "@/app/[locale]/(public)/legal/dpa/page";
import PrivacyPage from "@/app/[locale]/(public)/legal/privacy/page";
import SecurityDisclosurePage from "@/app/[locale]/(public)/legal/security-disclosure/page";
import SubprocessorsPage from "@/app/[locale]/(public)/legal/subprocessors/page";
import TermsPage from "@/app/[locale]/(public)/legal/terms/page";
import LoginPage from "@/app/[locale]/(public)/login/page";
import AcceptInvitePage from "@/app/[locale]/(public)/accept-invite/page";
import OrganizationOnboardingPage from "@/app/[locale]/(public)/organization-onboarding/page";
import ForbiddenPage from "@/app/[locale]/(public)/forbidden/page";
import LocaleNotFound from "@/app/[locale]/not-found";
import { StatusPage } from "@/components/public/pages/StatusPage";
import { ConsentProvider } from "@/components/consent/ConsentProvider";
import { CookieConsentBanner } from "@/components/consent/CookieConsentBanner";

const publicMessages = pickMessages(enMessages, PUBLIC_NAMESPACES);

function renderWithPublicMessages(ui: ReactNode) {
  return render(
    <NextIntlClientProvider
      locale="en"
      messages={publicMessages}
      onError={(error) => {
        throw error;
      }}
    >
      {ui}
    </NextIntlClientProvider>,
  );
}

const PAGES: Array<[string, ComponentType]> = [
  ["landing", Home],
  ["product", ProductPage],
  ["pricing", PricingPage],
  ["security", SecurityPage],
  ["solutions", SolutionsPage],
  ["solutions/client-portal", ClientPortalRoute],
  ["solutions/compliance", ComplianceRoute],
  ["solutions/hr", HRRoute],
  ["solutions/internal-knowledge", InternalKnowledgeRoute],
  ["solutions/legal", LegalSolutionRoute],
  ["solutions/operations", OperationsRoute],
  ["solutions/procurement", ProcurementRoute],
  ["solutions/research", ResearchRoute],
  ["solutions/sales", SalesRoute],
  ["solutions/support", SupportRoute],
  ["contact", ContactPage],
  ["changelog", ChangelogPage],
  ["legal/acceptable-use", AcceptableUsePage],
  ["legal/cookies", CookiesPage],
  ["legal/dpa", DpaPage],
  ["legal/privacy", PrivacyPage],
  ["legal/security-disclosure", SecurityDisclosurePage],
  ["legal/subprocessors", SubprocessorsPage],
  ["legal/terms", TermsPage],
  ["login", LoginPage],
  ["accept-invite", AcceptInvitePage],
  ["organization-onboarding", OrganizationOnboardingPage],
  ["not-found", LocaleNotFound],
];

describe("public pages render with PUBLIC_NAMESPACES only", () => {
  it.each(PAGES)("%s", (_name, Page) => {
    const { container } = renderWithPublicMessages(<Page />);
    expect(container.textContent?.trim().length).toBeGreaterThan(0);
  });

  it("forbidden", async () => {
    const page = await ForbiddenPage({});
    renderWithPublicMessages(page);
    expect(
      screen.getByRole("heading", { name: "Forbidden" }),
    ).toBeInTheDocument();
  });

  it("status (live data unavailable)", () => {
    const { container } = renderWithPublicMessages(
      <StatusPage snapshot={null} loadError="Unable to load." />,
    );
    expect(container.textContent).toContain("Status data unavailable");
  });

  it("fails loudly when a namespace is missing (guards this test)", () => {
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
    expect(() =>
      render(
        <NextIntlClientProvider
          locale="en"
          messages={pickMessages(enMessages, ["errors"])}
          onError={(error) => {
            throw error;
          }}
        >
          <Home />
        </NextIntlClientProvider>,
      ),
    ).toThrow(/MISSING_MESSAGE/);
    consoleError.mockRestore();
  });

  it("cookie consent banner", async () => {
    window.localStorage.clear();
    renderWithPublicMessages(
      <ConsentProvider>
        <CookieConsentBanner />
      </ConsentProvider>,
    );
    expect(
      await screen.findByRole("dialog", { name: "Cookie consent" }),
    ).toHaveTextContent("We use cookies");
  });
});

describe("public message payload", () => {
  it("contains no namespace that only the signed-in app uses", () => {
    const appOnly = APP_NAMESPACES.filter(
      (name) => !(PUBLIC_NAMESPACES as readonly string[]).includes(name),
    );
    expect(appOnly).toContain("adminPermissions");
    for (const name of appOnly) {
      expect(publicMessages).not.toHaveProperty(name);
    }
    expect(JSON.stringify(publicMessages)).not.toContain(
      JSON.stringify(enMessages.adminPermissions),
    );
  });
});
