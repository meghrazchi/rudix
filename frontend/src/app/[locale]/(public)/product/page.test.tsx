import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ProductPage, { generateMetadata } from "./page";

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

  it.each([
    ["en", "Product Overview | Rudix", "/en/product"],
    ["de", "Produktübersicht | Rudix", "/de/product"],
    ["es", "Resumen del producto | Rudix", "/es/product"],
    ["fr", "Présentation du produit | Rudix", "/fr/product"],
  ] as const)(
    "defines locale-aware SEO metadata for the /product route (%s)",
    async (locale, expectedTitle, expectedCanonicalSuffix) => {
      const metadata = await generateMetadata({
        params: Promise.resolve({ locale }),
      });

      expect(metadata.title).toBe(expectedTitle);
      expect(metadata.alternates?.canonical).toContain(expectedCanonicalSuffix);
    },
  );
});
