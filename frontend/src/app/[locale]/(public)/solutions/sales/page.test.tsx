import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { SalesSolutionPage } from "@/components/public/pages/SalesSolutionPage";

const originalEnv = { ...process.env };

function clearPublicEnv() {
  delete process.env.NEXT_PUBLIC_PUBLIC_DEMO_URL;
  delete process.env.NEXT_PUBLIC_PUBLIC_TRIAL_URL;
  delete process.env.NEXT_PUBLIC_PUBLIC_PRICING_URL;
}

describe("Sales solution page (/solutions/sales)", () => {
  beforeEach(() => {
    process.env = { ...originalEnv };
    clearPublicEnv();
  });

  afterEach(() => {
    process.env = { ...originalEnv };
  });

  it("renders the hero with sales-specific headline and badge", () => {
    render(<SalesSolutionPage />);

    expect(
      screen.getByRole("heading", {
        name: /Win deals with cited product intelligence\./i,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Sales Enablement Engine")).toBeInTheDocument();
  });

  it("renders the hero query mockup with citation badges", () => {
    render(<SalesSolutionPage />);

    expect(
      screen.getByText(/competitive advantages against AWS Bedrock/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Battlecard_v2\.pdf/)).toBeInTheDocument();
    expect(screen.getByText(/Pricing_Q3_Final\.xlsx/)).toBeInTheDocument();
    expect(screen.getByText("Sources Verified")).toBeInTheDocument();
  });

  it("renders the hero CTAs pointing to trial and demo", () => {
    render(<SalesSolutionPage />);

    expect(
      screen.getByRole("link", { name: /Start for free/i }),
    ).toHaveAttribute("href", "/signup");
    expect(screen.getByRole("link", { name: "View Demo" })).toHaveAttribute(
      "href",
      "/contact",
    );
  });

  it("renders the problem section with three friction cards", () => {
    render(<SalesSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "The Cost of Sales Friction" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Lost Case Studies" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Outdated Pricing" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Battlecard Friction" }),
    ).toBeInTheDocument();
  });

  it("renders document sources section with six sales asset types and images", () => {
    render(<SalesSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "Your knowledge, unified." }),
    ).toBeInTheDocument();
    expect(screen.getByText("Product Specs")).toBeInTheDocument();
    expect(screen.getByText("Case Studies")).toBeInTheDocument();
    expect(screen.getByText("RFP Templates")).toBeInTheDocument();
    expect(screen.getByText("Pricing Sheets")).toBeInTheDocument();
    expect(screen.getByText("Battlecards")).toBeInTheDocument();
    expect(screen.getByText("Proposal Decks")).toBeInTheDocument();

    expect(
      screen.getByAltText(
        "Professional sales collateral and technical product brochures",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByAltText(
        "Enterprise account executives collaborating in a sales strategy meeting",
      ),
    ).toBeInTheDocument();
  });

  it("renders example queries section with three sales questions", () => {
    render(<SalesSolutionPage />);

    expect(
      screen.getByRole("heading", { name: /Ask anything\./i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/"Which case study fits a healthcare prospect/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /"What are our competitive advantages against Enterprise-X\?"/i,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Can we offer a 15% discount/i),
    ).toBeInTheDocument();
  });

  it("renders the expanded query answer with citation", () => {
    render(<SalesSolutionPage />);

    expect(screen.getByText(/Q3 Battlecard/i)).toBeInTheDocument();
    expect(screen.getByText(/Native VPC deployment/i)).toBeInTheDocument();
  });

  it("renders the final CTA section with demo and pricing links", () => {
    render(<SalesSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "Ready to accelerate your deals?" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Schedule a Demo" }),
    ).toHaveAttribute("href", "/contact");
    expect(screen.getByRole("link", { name: "View Pricing" })).toHaveAttribute(
      "href",
      "/pricing",
    );
  });

  it("applies env-driven trial URL when configured", () => {
    process.env.NEXT_PUBLIC_PUBLIC_TRIAL_URL = "https://trial.example.com";

    render(<SalesSolutionPage />);

    expect(
      screen.getByRole("link", { name: /Start for free/i }),
    ).toHaveAttribute("href", "https://trial.example.com");
  });

  it("applies env-driven demo URL when configured", () => {
    process.env.NEXT_PUBLIC_PUBLIC_DEMO_URL = "https://demo.example.com";

    render(<SalesSolutionPage />);

    expect(
      screen.getByRole("link", { name: "Schedule a Demo" }),
    ).toHaveAttribute("href", "https://demo.example.com");
  });

  it("renders breadcrumb navigation back to solutions", () => {
    render(<SalesSolutionPage />);

    expect(screen.getByRole("link", { name: "Solutions" })).toHaveAttribute(
      "href",
      "/solutions",
    );
    expect(screen.getByText("Sales")).toBeInTheDocument();
  });
});
