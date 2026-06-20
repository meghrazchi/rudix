import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PricingPage, { generateMetadata } from "./page";

describe("Pricing public page", () => {
  it("renders pricing sections, plan cards, and CTA links", () => {
    render(<PricingPage />);

    expect(
      screen.getByRole("heading", {
        name: "Choose a plan for trusted document AI operations",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Plans for every rollout stage" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Usage and limit guidance" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Plan comparison" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Pricing FAQ" }),
    ).toBeInTheDocument();

    expect(
      screen.getByRole("heading", { name: "Starter" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Team" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Enterprise" }),
    ).toBeInTheDocument();

    expect(
      screen
        .getAllByRole("link", { name: "Start Trial" })
        .some((link) => link.getAttribute("href") === "/signup"),
    ).toBe(true);
    expect(
      screen.getAllByRole("link", { name: "Request Demo" }).length,
    ).toBeGreaterThanOrEqual(1);
    expect(
      screen
        .getAllByRole("link", { name: "Contact Sales" })
        .some((link) => link.getAttribute("href") === "/contact"),
    ).toBe(true);
    expect(
      screen
        .getAllByRole("link", { name: "Login" })
        .some((link) => link.getAttribute("href") === "/login"),
    ).toBe(true);
  });

  it("defines localized SEO metadata for /pricing", async () => {
    const metadata = await generateMetadata({
      params: Promise.resolve({ locale: "de" }),
    });

    expect(metadata.title).toBe("Preise | Rudix");
    expect(metadata.alternates?.canonical).toContain("/de/pricing");
  });
});
