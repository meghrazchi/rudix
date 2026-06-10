import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ProductPage, { metadata } from "./page";

describe("Product public page", () => {
  it("renders core product-overview sections and CTA links", () => {
    render(<ProductPage />);

    expect(
      screen.getByRole("heading", {
        name: /The Infrastructure for High-Fidelity/i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "The Rudix Engine Workflow" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Precision Document Management" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Grounded Answers with Citations",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Pipeline Explorer Visualizer",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Unified Admin Control",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Product FAQ",
      }),
    ).toBeInTheDocument();

    expect(
      screen.getAllByRole("link", { name: "Request Demo" }).length,
    ).toBeGreaterThanOrEqual(1);
    expect(
      screen.getByRole("link", { name: "View Pipeline Explorer" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "View Security Page" }),
    ).toBeInTheDocument();
  });

  it("defines unique SEO metadata for the /product route", () => {
    expect(metadata.title).toBe("Product Overview | Rudix");
    expect(metadata.description).toBe(
      "See how Rudix turns documents into indexed, citation-backed answers with evaluations, pipeline visibility, and governance-ready operations.",
    );
    expect(metadata.alternates?.canonical).toBe("/product");
  });
});
