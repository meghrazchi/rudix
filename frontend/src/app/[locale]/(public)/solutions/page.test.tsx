import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import SolutionsPage, { metadata } from "./page";

describe("Solutions public page", () => {
  it("renders six audience cards and key overview sections", () => {
    render(<SolutionsPage />);

    expect(
      screen.getByRole("heading", {
        name: "AI document Q&A for every team.",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Enterprise Use Cases" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Shared value across all solutions",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Choose Your Workflow" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "From scattered documents to trusted answers",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Example Question Matrix" }),
    ).toBeInTheDocument();

    expect(
      screen.getByRole("heading", { name: "Internal Knowledge" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "HR" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Support" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Legal" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Compliance" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Operations" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sales" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Procurement" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Research" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Client Portal" }),
    ).toBeInTheDocument();

    expect(screen.getByRole("link", { name: "HR solution" })).toHaveAttribute(
      "href",
      "/solutions/hr",
    );
    expect(
      screen.getByRole("link", { name: "Support solution" }),
    ).toHaveAttribute("href", "/solutions/support");
    expect(
      screen.getByRole("link", { name: "Legal solution" }),
    ).toHaveAttribute("href", "/solutions/legal");
    expect(
      screen.getByRole("link", { name: "Compliance solution" }),
    ).toHaveAttribute("href", "/solutions/compliance");
    expect(
      screen.getByRole("link", { name: "Operations solution" }),
    ).toHaveAttribute("href", "/solutions/operations");
    expect(
      screen.getByRole("link", { name: "Research solution" }),
    ).toHaveAttribute("href", "/solutions/research");
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute(
      "href",
      "/",
    );
    expect(
      screen.getAllByRole("link", { name: "Request Demo" }).length,
    ).toBeGreaterThanOrEqual(1);
    expect(
      screen.getByRole("link", { name: "View Product" }),
    ).toBeInTheDocument();
  });

  it("defines unique SEO metadata for /solutions", () => {
    expect(metadata.title).toBe("Solutions Overview | Rudix");
    expect(metadata.description).toBe(
      "Discover department-focused Rudix solutions for HR, Support, Legal, Compliance, Operations, and Research teams.",
    );
    expect(metadata.alternates?.canonical).toBe("/solutions");
  });
});
