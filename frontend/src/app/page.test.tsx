import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import Home from "@/app/page";

const originalEnv = { ...process.env };

describe("Public Landing Page", () => {
  beforeEach(() => {
    process.env = { ...originalEnv };
    delete process.env.NEXT_PUBLIC_LANDING_PRODUCT_URL;
    delete process.env.NEXT_PUBLIC_LANDING_SOLUTIONS_URL;
    delete process.env.NEXT_PUBLIC_LANDING_PRICING_URL;
    delete process.env.NEXT_PUBLIC_LANDING_DOCUMENTATION_URL;
    delete process.env.NEXT_PUBLIC_LANDING_TRIAL_URL;
    delete process.env.NEXT_PUBLIC_LANDING_DEMO_URL;
    delete process.env.NEXT_PUBLIC_LANDING_STATUS_URL;
    delete process.env.NEXT_PUBLIC_LANDING_CONTACT_URL;
    delete process.env.NEXT_PUBLIC_HELP_DOCS_URL;
    delete process.env.NEXT_PUBLIC_SUPPORT_URL;
  });

  afterEach(() => {
    process.env = { ...originalEnv };
  });

  it("renders all major landing sections", () => {
    render(<Home />);

    expect(
      screen.getByRole("heading", { name: /Scale Precision AI/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Native RAG Capabilities" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Built for Engineering Excellence" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Security First Infrastructure" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Deploy Production RAG Today" }),
    ).toBeInTheDocument();

    expect(screen.getByRole("link", { name: "Login" })).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Request Demo" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Start Free Trial" }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("link", { name: "Read Documentation" }).length,
    ).toBeGreaterThanOrEqual(1);
  });

  it("uses safe default CTA/navigation routes when landing env vars are not configured", () => {
    render(<Home />);

    expect(screen.getByRole("link", { name: "Product" })).toHaveAttribute(
      "href",
      "/dashboard",
    );
    expect(screen.getByRole("link", { name: "Solutions" })).toHaveAttribute(
      "href",
      "/documents",
    );
    expect(screen.getByRole("link", { name: "Pricing" })).toHaveAttribute(
      "href",
      "/settings",
    );
    expect(
      screen.getByRole("link", { name: "Start Free Trial" }),
    ).toHaveAttribute("href", "/signup");
    expect(screen.getByRole("link", { name: "Request Demo" })).toHaveAttribute(
      "href",
      "/login",
    );
    expect(
      screen.getAllByRole("link", { name: "Read Documentation" })[0],
    ).toHaveAttribute("href", "/documents");
  });

  it("applies env-driven landing links when configured", () => {
    process.env.NEXT_PUBLIC_LANDING_PRODUCT_URL = "/product-overview";
    process.env.NEXT_PUBLIC_LANDING_SOLUTIONS_URL = "/solutions";
    process.env.NEXT_PUBLIC_LANDING_PRICING_URL = "/pricing";
    process.env.NEXT_PUBLIC_LANDING_TRIAL_URL = "https://trial.example.com";
    process.env.NEXT_PUBLIC_LANDING_DEMO_URL = "https://demo.example.com";
    process.env.NEXT_PUBLIC_LANDING_DOCUMENTATION_URL =
      "https://docs.example.com";

    render(<Home />);

    expect(screen.getByRole("link", { name: "Product" })).toHaveAttribute(
      "href",
      "/product-overview",
    );
    expect(screen.getByRole("link", { name: "Solutions" })).toHaveAttribute(
      "href",
      "/solutions",
    );
    expect(screen.getByRole("link", { name: "Pricing" })).toHaveAttribute(
      "href",
      "/pricing",
    );
    expect(
      screen.getByRole("link", { name: "Start Free Trial" }),
    ).toHaveAttribute("href", "https://trial.example.com");
    expect(screen.getByRole("link", { name: "Request Demo" })).toHaveAttribute(
      "href",
      "https://demo.example.com",
    );
    expect(
      screen.getAllByRole("link", { name: "Read Documentation" })[0],
    ).toHaveAttribute("href", "https://docs.example.com");
  });
});
