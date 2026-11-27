import { render, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { LandingPage } from "@/components/public/pages/LandingPage";
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

function renderLanding() {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <LandingPage />
    </NextIntlClientProvider>,
  );
}

describe("LandingPage", () => {
  it("renders a single h1 with the hero headline", () => {
    renderLanding();

    const headings = screen.getAllByRole("heading", { level: 1 });
    expect(headings).toHaveLength(1);
    expect(headings[0]).toHaveTextContent(/Ask your documents\./);
  });

  it("routes hero CTAs to demo and document upload", () => {
    renderLanding();

    const hero = screen
      .getByRole("heading", { level: 1 })
      .closest("section") as HTMLElement;
    expect(
      within(hero).getByRole("link", { name: /Speak to us/ }),
    ).toHaveAttribute("href", "/contact");
    expect(
      within(hero).getByRole("link", { name: /Upload documents/ }),
    ).toHaveAttribute("href", "/documents");
  });

  it("labels each section with a heading for landmarks and SEO", () => {
    renderLanding();

    for (const name of [
      "Your team has the answers. They are just buried.",
      "Upload. Ask. Verify.",
      "Built for every team.",
      "Designed for private document workflows.",
      "Ready to turn your documents into an AI assistant?",
    ]) {
      expect(screen.getByRole("region", { name })).toBeInTheDocument();
    }
  });

  it("shows an accessible cited-answer preview with sources", () => {
    renderLanding();

    const preview = screen.getByRole("figure", {
      name: "Example of a cited answer in Rudix",
    });
    expect(within(preview).getByLabelText("Citation 1")).toBeInTheDocument();
    expect(within(preview).getByLabelText("Citation 2")).toBeInTheDocument();
    expect(within(preview).getByText("returns-policy.pdf")).toBeInTheDocument();
  });
});
