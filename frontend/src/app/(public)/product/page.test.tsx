import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ProductPage, { metadata } from "./page";

describe("Product public page", () => {
  it("renders core product-overview sections and CTA links", () => {
    render(<ProductPage />);

    expect(
      screen.getByRole("heading", {
        name: "AI Document Q&A for trusted enterprise decisions",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "How Rudix Works" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Capabilities Across the Product" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Operator and Admin Control Center",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "API-first, integration-ready foundation",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Product FAQ" }),
    ).toBeInTheDocument();

    expect(
      screen.getAllByRole("link", { name: "Request Demo" }).length,
    ).toBeGreaterThanOrEqual(1);
    expect(
      screen.getByRole("link", { name: "Start Trial or Log In" }),
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
