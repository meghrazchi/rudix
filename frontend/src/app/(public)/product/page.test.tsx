import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ProductPage from "./page";

describe("Product public page", () => {
  it("renders primary sections and CTA links", () => {
    render(<ProductPage />);

    expect(
      screen.getByRole("heading", {
        name: "Enterprise RAG platform for production teams",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "What You Can Build" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "From Documents to Trusted Answers",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Product FAQ" }),
    ).toBeInTheDocument();

    expect(
      screen.getAllByRole("link", { name: "Request Demo" }).length,
    ).toBeGreaterThanOrEqual(1);
    expect(
      screen.getByRole("link", { name: "Contact Sales" }),
    ).toBeInTheDocument();
  });
});
