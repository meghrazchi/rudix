import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { LegalSolutionPage } from "@/components/public/pages/LegalSolutionPage";

const originalEnv = { ...process.env };

function clearPublicEnv() {
  delete process.env.NEXT_PUBLIC_PUBLIC_DEMO_URL;
  delete process.env.NEXT_PUBLIC_PUBLIC_TRIAL_URL;
  delete process.env.NEXT_PUBLIC_PUBLIC_SECURITY_URL;
}

describe("Legal solution page (/solutions/legal)", () => {
  beforeEach(() => {
    process.env = { ...originalEnv };
    clearPublicEnv();
  });

  afterEach(() => {
    process.env = { ...originalEnv };
  });

  it("renders the hero with legal-specific headline and badge", () => {
    render(<LegalSolutionPage />);

    expect(
      screen.getByRole("heading", {
        name: "Ask contracts and policies with source-backed answers.",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Legal Intelligence")).toBeInTheDocument();
  });

  it("renders the problem section with three pain-point cards", () => {
    render(<LegalSolutionPage />);

    expect(
      screen.getByRole("heading", {
        name: /Contracts are too important to search manually/i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Long Contracts" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Repeated Questions" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Missed Deadlines" }),
    ).toBeInTheDocument();
  });

  it("renders document sources section with six legal document types", () => {
    render(<LegalSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "Built for every legal asset." }),
    ).toBeInTheDocument();
    expect(screen.getByText("Customer contracts")).toBeInTheDocument();
    expect(screen.getByText("Vendor agreements")).toBeInTheDocument();
    expect(screen.getByText("NDAs")).toBeInTheDocument();
    expect(screen.getByText("DPAs")).toBeInTheDocument();
    expect(screen.getByText("Terms of service")).toBeInTheDocument();
    expect(screen.getByText("Legal guidance")).toBeInTheDocument();
  });

  it("renders example questions section on dark background", () => {
    render(<LegalSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "Ask your data anything." }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/"What is the termination notice period\?"/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/"Does this contract renew automatically\?"/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/"Is there a limitation of liability clause\?"/),
    ).toBeInTheDocument();
  });

  it("renders citations section with contract viewer and trust copy", () => {
    render(<LegalSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "Trust the source." }),
    ).toBeInTheDocument();
    expect(screen.getByText(/MSA_Enterprise_Final\.pdf/)).toBeInTheDocument();
    expect(screen.getByText(/Deep linking/i)).toBeInTheDocument();
    expect(screen.getByText(/Audit trails/i)).toBeInTheDocument();
  });

  it("renders responsible-use disclaimer", () => {
    render(<LegalSolutionPage />);

    expect(screen.getByText("Responsible use")).toBeInTheDocument();
    expect(
      screen.getByText(
        /does not replace attorney review or constitute legal advice/i,
      ),
    ).toBeInTheDocument();
  });

  it("renders Security and Compliance link in the citations section", () => {
    render(<LegalSolutionPage />);

    const securityLink = screen.getByRole("link", {
      name: /Security.*Compliance/i,
    });
    expect(securityLink).toHaveAttribute("href", "/security");
  });

  it("renders the final CTA section with trial and demo links", () => {
    render(<LegalSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "Find contract answers faster." }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Start Free Trial" }),
    ).toHaveAttribute("href", "/signup");
    expect(screen.getByRole("link", { name: "Book a Demo" })).toHaveAttribute(
      "href",
      "/contact",
    );
  });

  it("renders hero CTA link pointing to demo", () => {
    render(<LegalSolutionPage />);

    const heroLink = screen.getByRole("link", {
      name: /Speak to us about legal workflows/i,
    });
    expect(heroLink).toHaveAttribute("href", "/contact");
  });

  it("applies env-driven demo URL when configured", () => {
    process.env.NEXT_PUBLIC_PUBLIC_DEMO_URL = "https://demo.example.com";

    render(<LegalSolutionPage />);

    const heroLink = screen.getByRole("link", {
      name: /Speak to us about legal workflows/i,
    });
    expect(heroLink).toHaveAttribute("href", "https://demo.example.com");
  });

  it("renders breadcrumb navigation back to solutions", () => {
    render(<LegalSolutionPage />);

    expect(screen.getByRole("link", { name: "Solutions" })).toHaveAttribute(
      "href",
      "/solutions",
    );
    expect(screen.getByText("Legal")).toBeInTheDocument();
  });
});
