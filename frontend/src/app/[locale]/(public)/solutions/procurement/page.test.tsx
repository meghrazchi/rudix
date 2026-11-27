import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ProcurementSolutionPage } from "@/components/public/pages/ProcurementSolutionPage";

const originalEnv = { ...process.env };

function clearPublicEnv() {
  delete process.env.NEXT_PUBLIC_PUBLIC_DEMO_URL;
}

describe("Procurement solution page (/solutions/procurement)", () => {
  beforeEach(() => {
    process.env = { ...originalEnv };
    clearPublicEnv();
  });

  afterEach(() => {
    process.env = { ...originalEnv };
  });

  it("renders the hero with procurement-specific headline and badge", () => {
    render(<ProcurementSolutionPage />);

    expect(
      screen.getByRole("heading", {
        name: "Evaluate vendors with AI-powered document review.",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Procurement & Vendor Review")).toBeInTheDocument();
  });

  it("renders the hero image with descriptive alt text", () => {
    render(<ProcurementSolutionPage />);

    expect(
      screen.getByAltText(
        "Procurement analytics dashboard showing vendor evaluation data",
      ),
    ).toBeInTheDocument();
  });

  it("renders the hero CTA pointing to the demo request, not signup", () => {
    render(<ProcurementSolutionPage />);

    expect(screen.getByRole("link", { name: "View Demo" })).toHaveAttribute(
      "href",
      "/contact",
    );
    expect(
      screen.queryByRole("link", { name: "Start Review" }),
    ).not.toBeInTheDocument();
    // Self-service signup is disabled; no CTA may lead to /signup.
    expect(document.querySelector('a[href*="signup"]')).toBeNull();
  });

  it("renders the problem section with three bottleneck cards", () => {
    render(<ProcurementSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "The Procurement Bottleneck" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Long security questionnaires" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Manual contract comparison" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Risk assessment friction" }),
    ).toBeInTheDocument();
  });

  it("renders document sources section with four procurement document types", () => {
    render(<ProcurementSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "Unified Knowledge Ingestion" }),
    ).toBeInTheDocument();
    expect(screen.getByText("SOC2 Reports")).toBeInTheDocument();
    expect(screen.getByText("RFP Responses")).toBeInTheDocument();
    expect(screen.getByText("Vendor Contracts")).toBeInTheDocument();
    expect(screen.getByText("Security Questionnaires")).toBeInTheDocument();
    expect(screen.getByText("OCR for scanned documents")).toBeInTheDocument();
  });

  it("renders the four-step engine section", () => {
    render(<ProcurementSolutionPage />);

    expect(
      screen.getByRole("heading", {
        name: "The Rudix Engine for Procurement",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Deep Semantic Indexing" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Automated Extraction" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Flag Risk" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Approve" }),
    ).toBeInTheDocument();
  });

  it("renders example queries with cited answers", () => {
    render(<ProcurementSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "Ask Anything. Get Citations." }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/data residency requirements for the EU/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Summarize the security controls in this SOC2 report/i),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Rudix Analysis:").length).toBe(2);
    expect(screen.getByText(/Frankfurt/i)).toBeInTheDocument();
  });

  it("renders the final CTA with a single demo link", () => {
    render(<ProcurementSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "Stop Reviewing, Start Deciding." }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Schedule a Demo" }),
    ).toHaveAttribute("href", "/contact");
    expect(
      screen.queryByRole("link", { name: "Get Started Free" }),
    ).not.toBeInTheDocument();
  });

  it("renders responsible-use disclaimer in the final CTA", () => {
    render(<ProcurementSolutionPage />);

    expect(
      screen.getByText(
        /does not replace legal or procurement approval workflows/i,
      ),
    ).toBeInTheDocument();
  });

  it("applies env-driven demo URL when configured", () => {
    process.env.NEXT_PUBLIC_PUBLIC_DEMO_URL = "https://demo.example.com";

    render(<ProcurementSolutionPage />);

    expect(
      screen.getByRole("link", { name: "Schedule a Demo" }),
    ).toHaveAttribute("href", "https://demo.example.com");
  });

  it("renders breadcrumb navigation back to solutions", () => {
    render(<ProcurementSolutionPage />);

    expect(screen.getByRole("link", { name: "Solutions" })).toHaveAttribute(
      "href",
      "/solutions",
    );
    expect(screen.getByText("Procurement")).toBeInTheDocument();
  });
});
