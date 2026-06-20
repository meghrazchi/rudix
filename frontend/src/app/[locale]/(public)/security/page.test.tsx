import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import SecurityPage, { generateMetadata } from "./page";

describe("Security public page", () => {
  it("renders security and trust sections with route CTAs", () => {
    render(<SecurityPage />);

    expect(
      screen.getByRole("heading", {
        name: "Security and governance for private document AI",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Security pillars" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Document handling lifecycle" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Access and governance",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Compliance readiness",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Retention and deletion",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Security FAQ" }),
    ).toBeInTheDocument();

    expect(
      screen.getByRole("link", { name: "Request Security Review" }),
    ).toHaveAttribute("href", "/contact");
    expect(
      screen.getByRole("link", { name: "View Architecture" }),
    ).toHaveAttribute("href", "/documents");
    expect(
      screen.getAllByRole("link", { name: "Talk to Security" })[0],
    ).toHaveAttribute("href", "/contact");
    expect(
      screen.getAllByRole("link", { name: "Request Demo" }).length,
    ).toBeGreaterThanOrEqual(1);
  });

  it("defines localized SEO metadata for /security", async () => {
    const metadata = await generateMetadata({
      params: Promise.resolve({ locale: "es" }),
    });

    expect(metadata.title).toBe("Seguridad y confianza | Rudix");
    expect(metadata.alternates?.canonical).toContain("/es/security");
  });
});
