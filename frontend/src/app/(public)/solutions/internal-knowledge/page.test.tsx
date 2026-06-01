import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { InternalKnowledgeSolutionPage } from "@/components/public/pages/InternalKnowledgeSolutionPage";

const originalEnv = { ...process.env };

function clearPublicEnv() {
  delete process.env.NEXT_PUBLIC_PUBLIC_DEMO_URL;
  delete process.env.NEXT_PUBLIC_PUBLIC_TRIAL_URL;
  delete process.env.NEXT_PUBLIC_PUBLIC_PRICING_URL;
}

describe("Internal Knowledge solution page (/solutions/internal-knowledge)", () => {
  beforeEach(() => {
    process.env = { ...originalEnv };
    clearPublicEnv();
  });

  afterEach(() => {
    process.env = { ...originalEnv };
  });

  it("renders the hero with knowledge-specific headline and badge", () => {
    render(<InternalKnowledgeSolutionPage />);

    expect(
      screen.getByRole("heading", {
        name: /Your team's knowledge, instantly accessible\./i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Internal Knowledge Assistant"),
    ).toBeInTheDocument();
  });

  it("renders the hero chat mockup with citation", () => {
    render(<InternalKnowledgeSolutionPage />);

    expect(
      screen.getByText(/remote work stipends for international employees/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Global Employee Handbook/i)).toBeInTheDocument();
    expect(screen.getByText(/SOP-HR-042\.pdf/i)).toBeInTheDocument();
    expect(
      screen.getByText(/\$500 initial setup stipend/i),
    ).toBeInTheDocument();
  });

  it("renders hero CTAs pointing to trial and demo", () => {
    render(<InternalKnowledgeSolutionPage />);

    expect(screen.getByRole("link", { name: "Get Started" })).toHaveAttribute(
      "href",
      "/signup",
    );
    expect(screen.getByRole("link", { name: "Watch Demo" })).toHaveAttribute(
      "href",
      "/contact",
    );
  });

  it("renders the problem section with three friction cards", () => {
    render(<InternalKnowledgeSolutionPage />);

    expect(
      screen.getByRole("heading", {
        name: "The high cost of hidden knowledge",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Information Silos" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Onboarding Friction" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Slack Overload" }),
    ).toBeInTheDocument();
  });

  it("renders document support section with four doc types and three features", () => {
    render(<InternalKnowledgeSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "One Brain, Every Document" }),
    ).toBeInTheDocument();
    expect(screen.getByText("SOPs")).toBeInTheDocument();
    expect(screen.getByText("Handbooks")).toBeInTheDocument();
    expect(screen.getByText("Playbooks")).toBeInTheDocument();
    expect(screen.getByText("Manuals")).toBeInTheDocument();
    expect(
      screen.getByText("Preserves original citations and links"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Automatic re-indexing on file updates"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Strict data permission mirroring"),
    ).toBeInTheDocument();
  });

  it("renders the four-step Rudix Flow section with technical card", () => {
    render(<InternalKnowledgeSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "The Rudix Flow" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Upload SOPs" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Vector Index" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Ask Anything" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Verify & Cite" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/RAG ENGINE STATUS: ACTIVE/i)).toBeInTheDocument();
  });

  it("renders the four example query cards", () => {
    render(<InternalKnowledgeSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "Ask Rudix Anything" }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByText(/"What is the budget approval process\?"/i).length,
    ).toBeGreaterThanOrEqual(1);
    expect(
      screen.getByText(/"Where is the brand style guide\?"/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/"How do I request temporary VPN access\?"/),
    ).toBeInTheDocument();
    expect(screen.getByText(/working from abroad/i)).toBeInTheDocument();
  });

  it("renders the final CTA with demo and pricing links", () => {
    render(<InternalKnowledgeSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "Stop searching. Start knowing." }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Speak to us" })).toHaveAttribute(
      "href",
      "/contact",
    );
    expect(screen.getByRole("link", { name: "View Pricing" })).toHaveAttribute(
      "href",
      "/pricing",
    );
  });

  it("mentions citation-backed answers and access control", () => {
    render(<InternalKnowledgeSolutionPage />);

    expect(
      screen.getByText(/Strict data permission mirroring/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/verifiable sources/i)).toBeInTheDocument();
  });

  it("links to at least three related pages", () => {
    render(<InternalKnowledgeSolutionPage />);

    const links = screen.getAllByRole("link");
    const hrefs = links.map((l) => l.getAttribute("href")).filter(Boolean);
    const uniqueExternalRoutes = new Set(
      hrefs.filter((h) => h && h !== "/" && h !== "/solutions"),
    );
    expect(uniqueExternalRoutes.size).toBeGreaterThanOrEqual(3);
  });

  it("applies env-driven trial URL when configured", () => {
    process.env.NEXT_PUBLIC_PUBLIC_TRIAL_URL = "https://trial.example.com";

    render(<InternalKnowledgeSolutionPage />);

    expect(screen.getByRole("link", { name: "Get Started" })).toHaveAttribute(
      "href",
      "https://trial.example.com",
    );
  });

  it("applies env-driven demo URL when configured", () => {
    process.env.NEXT_PUBLIC_PUBLIC_DEMO_URL = "https://demo.example.com";

    render(<InternalKnowledgeSolutionPage />);

    expect(screen.getByRole("link", { name: "Speak to us" })).toHaveAttribute(
      "href",
      "https://demo.example.com",
    );
  });

  it("renders breadcrumb navigation back to solutions", () => {
    render(<InternalKnowledgeSolutionPage />);

    expect(screen.getByRole("link", { name: "Solutions" })).toHaveAttribute(
      "href",
      "/solutions",
    );
    expect(screen.getByText("Internal Knowledge")).toBeInTheDocument();
  });
});
