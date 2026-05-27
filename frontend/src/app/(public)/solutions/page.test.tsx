import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import SolutionsPage, { metadata } from "./page";

describe("Solutions public page", () => {
  it("renders six audience cards and key overview sections", () => {
    render(<SolutionsPage />);

    expect(
      screen.getByRole("heading", {
        name: "Trusted AI answers for every document-driven team",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Solutions by Department" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Shared value across all solutions",
      }),
    ).toBeInTheDocument();

    expect(
      screen.getByRole("heading", { name: "HR Knowledge Assistant" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Customer Support Resolution Hub",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Legal Review and Obligation Assist",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Compliance Evidence Navigator",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Operations Runbook Intelligence" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Research and Strategy Briefing" }),
    ).toBeInTheDocument();

    expect(
      screen.getByRole("link", { name: "Explore HR solution" }),
    ).toHaveAttribute("href", "/solutions/hr");
    expect(
      screen.getByRole("link", { name: "Explore Support solution" }),
    ).toHaveAttribute("href", "/solutions/support");
    expect(
      screen.getByRole("link", { name: "Explore Legal solution" }),
    ).toHaveAttribute("href", "/solutions/legal");
    expect(
      screen.getByRole("link", { name: "Explore Compliance solution" }),
    ).toHaveAttribute("href", "/solutions/compliance");
    expect(
      screen.getByRole("link", { name: "Explore Operations solution" }),
    ).toHaveAttribute("href", "/solutions/operations");
    expect(
      screen.getByRole("link", { name: "Explore Research solution" }),
    ).toHaveAttribute("href", "/solutions/research");
  });

  it("defines unique SEO metadata for /solutions", () => {
    expect(metadata.title).toBe("Solutions Overview | Rudix");
    expect(metadata.description).toBe(
      "Discover department-focused Rudix solutions for HR, Support, Legal, Compliance, Operations, and Research teams.",
    );
    expect(metadata.alternates?.canonical).toBe("/solutions");
  });
});
