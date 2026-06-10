import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ClientPortalSolutionPage } from "@/components/public/pages/ClientPortalSolutionPage";

const originalEnv = { ...process.env };

function clearPublicEnv() {
  delete process.env.NEXT_PUBLIC_PUBLIC_DEMO_URL;
  delete process.env.NEXT_PUBLIC_PUBLIC_TRIAL_URL;
  delete process.env.NEXT_PUBLIC_PUBLIC_PRICING_URL;
}

describe("Client Portal solution page (/solutions/client-portal)", () => {
  beforeEach(() => {
    process.env = { ...originalEnv };
    clearPublicEnv();
  });

  afterEach(() => {
    process.env = { ...originalEnv };
  });

  it("renders the hero with client-portal-specific headline and badge", () => {
    render(<ClientPortalSolutionPage />);

    expect(
      screen.getByRole("heading", {
        name: /Give clients instant answers from your approved documentation\./i,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Client Knowledge Portal")).toBeInTheDocument();
  });

  it("renders the hero CTAs pointing to trial and demo", () => {
    render(<ClientPortalSolutionPage />);

    expect(
      screen.getByRole("link", { name: /Start Free Trial/i }),
    ).toHaveAttribute("href", "/signup");
    expect(screen.getByRole("link", { name: "Request Demo" })).toHaveAttribute(
      "href",
      "/contact",
    );
  });

  it("renders the problem section with three friction cards", () => {
    render(<ClientPortalSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "The Client Knowledge Gap" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Repeated client questions" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Scattered onboarding docs" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Slow implementation handoffs" }),
    ).toBeInTheDocument();
  });

  it("renders the document sources section with six source types", () => {
    render(<ClientPortalSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "Approved sources, scoped access." }),
    ).toBeInTheDocument();
    expect(screen.getByText("Onboarding Guides")).toBeInTheDocument();
    expect(screen.getByText("API Documentation")).toBeInTheDocument();
    expect(screen.getByText("Implementation Guides")).toBeInTheDocument();
    expect(screen.getByText("Knowledge Base")).toBeInTheDocument();
    expect(screen.getByText("Product Guides")).toBeInTheDocument();
    expect(screen.getByText("Enablement Materials")).toBeInTheDocument();
  });

  it("renders the workflow section with four steps", () => {
    render(<ClientPortalSolutionPage />);

    expect(
      screen.getByRole("heading", {
        name: /From document approval to client Q&A/i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Approve Client-Facing Docs" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Index & Scope Access" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Expose Q&A" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Verify & Improve" }),
    ).toBeInTheDocument();
  });

  it("renders the use cases section with five use case cards", () => {
    render(<ClientPortalSolutionPage />);

    expect(
      screen.getByRole("heading", {
        name: "Built for every client touchpoint",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Customer Onboarding" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Implementation Docs" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Partner Enablement" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Support Knowledge" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Account Handoff" }),
    ).toBeInTheDocument();
  });

  it("renders the example queries section with cited answers", () => {
    render(<ClientPortalSolutionPage />);

    expect(
      screen.getByRole("heading", { name: /Cited answers\. Every time\./i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /How do I configure SAML-based SSO for my organization/i,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/What data is retained after I close my account/i),
    ).toBeInTheDocument();
    expect(screen.getByText("Admin Setup Guide v3.2")).toBeInTheDocument();
    expect(screen.getByText("Data Retention Policy")).toBeInTheDocument();
  });

  it("renders the related solutions section with expected links", () => {
    render(<ClientPortalSolutionPage />);

    expect(screen.getByRole("link", { name: "Support" })).toHaveAttribute(
      "href",
      "/solutions/support",
    );
    expect(screen.getByRole("link", { name: "Sales" })).toHaveAttribute(
      "href",
      "/solutions/sales",
    );
    expect(
      screen.getByRole("link", { name: "Internal Knowledge" }),
    ).toHaveAttribute("href", "/solutions/internal-knowledge");
    expect(screen.getByRole("link", { name: "Security" })).toHaveAttribute(
      "href",
      "/security",
    );
  });

  it("renders the final CTA section with demo and trial links", () => {
    render(<ClientPortalSolutionPage />);

    expect(
      screen.getByRole("heading", {
        name: "Your clients deserve better answers.",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Schedule a Demo" }),
    ).toHaveAttribute("href", "/contact");
    expect(
      screen.getByRole("link", { name: "Get Started Free" }),
    ).toHaveAttribute("href", "/signup");
  });

  it("applies env-driven trial URL when configured", () => {
    process.env.NEXT_PUBLIC_PUBLIC_TRIAL_URL = "https://trial.example.com";

    render(<ClientPortalSolutionPage />);

    expect(
      screen.getByRole("link", { name: /Start Free Trial/i }),
    ).toHaveAttribute("href", "https://trial.example.com");
    expect(
      screen.getByRole("link", { name: /Get Started Free/i }),
    ).toHaveAttribute("href", "https://trial.example.com");
  });

  it("applies env-driven demo URL when configured", () => {
    process.env.NEXT_PUBLIC_PUBLIC_DEMO_URL = "https://demo.example.com";

    render(<ClientPortalSolutionPage />);

    expect(
      screen.getByRole("link", { name: "Schedule a Demo" }),
    ).toHaveAttribute("href", "https://demo.example.com");
  });

  it("renders breadcrumb navigation back to solutions", () => {
    render(<ClientPortalSolutionPage />);

    expect(screen.getByRole("link", { name: "Solutions" })).toHaveAttribute(
      "href",
      "/solutions",
    );
    expect(screen.getByText("Client Portal")).toBeInTheDocument();
  });
});
