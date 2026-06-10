import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PricingPage, { metadata } from "./page";

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

  it("defines unique SEO metadata for /pricing", () => {
    expect(metadata.title).toBe("Pricing | Rudix");
    expect(metadata.description).toBe(
      "Compare Rudix plans for document AI, RAG chat, evaluations, and governance with configurable packaging guidance.",
    );
    expect(metadata.alternates?.canonical).toBe("/pricing");
  });
});
