import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ComplianceSolutionPage } from "@/components/public/pages/ComplianceSolutionPage";

const originalEnv = { ...process.env };

function clearPublicEnv() {
  delete process.env.NEXT_PUBLIC_PUBLIC_DEMO_URL;
  delete process.env.NEXT_PUBLIC_PUBLIC_SECURITY_URL;
  delete process.env.NEXT_PUBLIC_PUBLIC_DOCS_URL;
}

describe("Compliance solution page (/solutions/compliance)", () => {
  beforeEach(() => {
    process.env = { ...originalEnv };
    clearPublicEnv();
  });

  afterEach(() => {
    process.env = { ...originalEnv };
  });

  it("renders the hero with compliance-specific headline and badge", () => {
    render(<ComplianceSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "Find audit evidence faster." }),
    ).toBeInTheDocument();
    expect(screen.getByText("Solution: Compliance")).toBeInTheDocument();
  });

  it("renders the hero compliance engine mockup with example sources", () => {
    render(<ComplianceSolutionPage />);

    expect(screen.getByText("Compliance Engine")).toBeInTheDocument();
    expect(
      screen.getByText(/What supports our access review process/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/SOC2_Evidence_Q4\.pdf/i)).toBeInTheDocument();
    expect(screen.getByText(/Access_Policy_v2\.docx/i)).toBeInTheDocument();
  });

  it("renders the problem section with three pain-point cards", () => {
    render(<ComplianceSolutionPage />);

    expect(
      screen.getByRole("heading", {
        name: /Audit evidence is difficult to find when it is spread across files/i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Evidence Fragmentation" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Traceability Gaps" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Manual Collection Drain" }),
    ).toBeInTheDocument();
  });

  it("renders document sources section with five compliance document types", () => {
    render(<ComplianceSolutionPage />);

    expect(
      screen.getByRole("heading", {
        name: "Upload everything. Find anything.",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Security Policies")).toBeInTheDocument();
    expect(screen.getByText("Audit Evidence")).toBeInTheDocument();
    expect(screen.getByText("Risk Assessments")).toBeInTheDocument();
    expect(screen.getByText("Access Reviews")).toBeInTheDocument();
    expect(screen.getByText("Incident Response")).toBeInTheDocument();
  });

  it("renders example questions section with three compliance queries", () => {
    render(<ComplianceSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "Interrogate your evidence." }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/"Where is the data retention policy\?"/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/"What evidence supports access reviews\?"/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/"Which policy mentions encryption requirements\?"/),
    ).toBeInTheDocument();
  });

  it("renders the trust section with three governance features", () => {
    render(<ComplianceSolutionPage />);

    expect(
      screen.getByRole("heading", {
        name: "Built for enterprise-grade trust.",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Audit-friendly source references" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Permission-filtered retrieval" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Admin activity logs" }),
    ).toBeInTheDocument();
  });

  it("renders the activity stream with audit log items", () => {
    render(<ComplianceSolutionPage />);

    expect(screen.getByText("Activity Stream")).toBeInTheDocument();
    expect(screen.getByText(/SOC2_v2/)).toBeInTheDocument();
    expect(screen.getByText(/ISO_Annex_A/)).toBeInTheDocument();
    expect(screen.getByText(/Q4_Evidence_01/)).toBeInTheDocument();
  });

  it("renders compliance disclaimer without certification claims", () => {
    render(<ComplianceSolutionPage />);

    expect(screen.getByText("Compliance disclaimer")).toBeInTheDocument();
    expect(
      screen.getByText(
        /does not issue certifications or replace auditor review/i,
      ),
    ).toBeInTheDocument();
  });

  it("renders Security and Compliance link", () => {
    render(<ComplianceSolutionPage />);

    const securityLink = screen.getByRole("link", {
      name: /Security.*Compliance/i,
    });
    expect(securityLink).toHaveAttribute("href", "/security");
  });

  it("renders the final CTA section with demo and docs links", () => {
    render(<ComplianceSolutionPage />);

    expect(
      screen.getByRole("heading", {
        name: "Make compliance evidence easier to find.",
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Speak to us" })).toHaveAttribute(
      "href",
      "/contact",
    );
    expect(
      screen.getByRole("link", { name: "View Documentation" }),
    ).toHaveAttribute("href", "/documents");
  });

  it("applies env-driven demo URL when configured", () => {
    process.env.NEXT_PUBLIC_PUBLIC_DEMO_URL = "https://demo.example.com";

    render(<ComplianceSolutionPage />);

    const heroLink = screen.getByRole("link", {
      name: "Speak to us about compliance",
    });
    expect(heroLink).toHaveAttribute("href", "https://demo.example.com");
  });

  it("renders breadcrumb navigation back to solutions", () => {
    render(<ComplianceSolutionPage />);

    expect(screen.getByRole("link", { name: "Solutions" })).toHaveAttribute(
      "href",
      "/solutions",
    );
    expect(screen.getByText("Compliance")).toBeInTheDocument();
  });
});
