import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { HRSolutionPage } from "@/components/public/pages/HRSolutionPage";
import { SolutionDetailPage } from "@/components/public/pages/SolutionDetailPage";
import { getSolutionAudienceBySlug } from "@/lib/public-site/solutions";

const originalEnv = { ...process.env };

function clearPublicEnv() {
  delete process.env.NEXT_PUBLIC_PUBLIC_DEMO_URL;
  delete process.env.NEXT_PUBLIC_PUBLIC_PRODUCT_URL;
  delete process.env.NEXT_PUBLIC_PUBLIC_SOLUTIONS_URL;
}

describe("HR solution page (/solutions/hr)", () => {
  beforeEach(() => {
    process.env = { ...originalEnv };
    clearPublicEnv();
  });

  afterEach(() => {
    process.env = { ...originalEnv };
  });

  it("renders the hero with HR-specific headline and badge", () => {
    render(<HRSolutionPage />);

    expect(
      screen.getByRole("heading", {
        name: "HR answers from your actual policies.",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Enterprise HR Solutions")).toBeInTheDocument();
  });

  it("renders the problem section with three pain-point cards", () => {
    render(<HRSolutionPage />);

    expect(
      screen.getByRole("heading", {
        name: /HR teams answer the same questions/i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Repeated Questions" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Hard to Search" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Accuracy Gaps" }),
    ).toBeInTheDocument();
  });

  it("renders the 4-step policy infrastructure flow", () => {
    render(<HRSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "Policy infrastructure flow" }),
    ).toBeInTheDocument();
    expect(screen.getByText("HR uploads policies")).toBeInTheDocument();
    expect(screen.getByText("Rudix indexes")).toBeInTheDocument();
    expect(screen.getByText("Employees ask")).toBeInTheDocument();
    expect(screen.getByText("Cited answers")).toBeInTheDocument();
  });

  it("renders supported document sources section", () => {
    render(<HRSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "Supported document sources" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Employee handbook")).toBeInTheDocument();
    expect(screen.getByText("Leave and time-off policies")).toBeInTheDocument();
    expect(screen.getByText("Onboarding checklist")).toBeInTheDocument();
  });

  it("renders example questions with accordion items", () => {
    render(<HRSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "Instant clarity for every query." }),
    ).toBeInTheDocument();
    // use getAllByText since the parental leave question also appears in the flow section
    expect(
      screen.getAllByText(/"What is the parental leave policy\?"/i).length,
    ).toBeGreaterThanOrEqual(1);
    expect(
      screen.getByText(/"How many vacation days do I get\?"/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/"How do I submit an expense claim\?"/),
    ).toBeInTheDocument();
    // not-found behavior question
    expect(
      screen.getByText(/What happens if my question is not covered/i),
    ).toBeInTheDocument();
  });

  it("renders security section with usage note", () => {
    render(<HRSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "Built for HR data sensitivity" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/does not make employment decisions/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Role-scoped access/i)).toBeInTheDocument();
    expect(screen.getByText(/Complete audit log/i)).toBeInTheDocument();
  });

  it("renders CTA links pointing to demo and solutions", () => {
    render(<HRSolutionPage />);

    const demoLinks = screen.getAllByRole("link", {
      name: "Speak to us about HR",
    });
    expect(demoLinks.length).toBeGreaterThanOrEqual(1);
    demoLinks.forEach((link) =>
      expect(link).toHaveAttribute("href", "/contact"),
    );

    const solutionsLinks = screen.getAllByRole("link", {
      name: "View all solutions",
    });
    expect(solutionsLinks.length).toBeGreaterThanOrEqual(1);
    solutionsLinks.forEach((link) =>
      expect(link).toHaveAttribute("href", "/solutions"),
    );
  });

  it("applies env-driven demo URL when configured", () => {
    process.env.NEXT_PUBLIC_PUBLIC_DEMO_URL = "https://demo.example.com";

    render(<HRSolutionPage />);

    const demoLinks = screen.getAllByRole("link", {
      name: "Speak to us about HR",
    });
    demoLinks.forEach((link) =>
      expect(link).toHaveAttribute("href", "https://demo.example.com"),
    );
  });

  it("renders breadcrumb navigation back to solutions", () => {
    render(<HRSolutionPage />);

    expect(screen.getByRole("link", { name: "Solutions" })).toHaveAttribute(
      "href",
      "/solutions",
    );
  });
});

describe("Generic solution detail page — other slugs still work", () => {
  it("renders the Compliance solution without HR-specific sections", () => {
    const solution = getSolutionAudienceBySlug("compliance");
    render(<SolutionDetailPage solution={solution!} />);

    expect(
      screen.getByRole("heading", { name: "Compliance Evidence Navigator" }),
    ).toBeInTheDocument();
    // HR-only sections should not appear
    expect(
      screen.queryByRole("heading", { name: "Policy infrastructure flow" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Built for HR data sensitivity" }),
    ).not.toBeInTheDocument();
  });
});
