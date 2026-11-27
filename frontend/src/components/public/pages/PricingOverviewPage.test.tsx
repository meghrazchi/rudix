import { render, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { PricingOverviewPage } from "@/components/public/pages/PricingOverviewPage";
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

function renderPricing() {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <PricingOverviewPage />
    </NextIntlClientProvider>,
  );
}

function planCard(name: string): HTMLElement {
  return screen
    .getByRole("heading", { level: 3, name })
    .closest("li") as HTMLElement;
}

describe("PricingOverviewPage", () => {
  it("routes every plan CTA to a conversation, never to self-signup", () => {
    renderPricing();

    expect(
      within(planCard("Starter")).getByRole("link", { name: "Request Access" }),
    ).toHaveAttribute("href", "/contact");
    expect(
      within(planCard("Team")).getByRole("link", { name: "Request Demo" }),
    ).toHaveAttribute("href", "/contact");
    expect(
      within(planCard("Enterprise")).getByRole("link", {
        name: "Contact Sales",
      }),
    ).toHaveAttribute("href", "/contact");
  });

  it("features the Team plan and shows contact pricing, not numbers", () => {
    const { container } = renderPricing();

    expect(planCard("Team")).toHaveTextContent("Most selected for rollout");
    expect(screen.getAllByText("Contact us")).toHaveLength(3);
    expect(container.textContent).not.toMatch(/[$€£]\s?\d/);
  });

  it("does not show internal notes in public copy", () => {
    const { container } = renderPricing();

    expect(container).not.toHaveTextContent(/placeholders/i);
    expect(container).not.toHaveTextContent(/Mobile view uses/i);
  });

  it("renders an accessible comparison table", () => {
    renderPricing();

    const table = screen.getByRole("table", { name: "Capabilities by plan" });
    expect(within(table).getAllByRole("columnheader")).toHaveLength(4);
    expect(within(table).getAllByRole("rowheader")).toHaveLength(7);
    expect(
      within(table).getByRole("rowheader", { name: "Support level" }),
    ).toBeInTheDocument();
  });
});
