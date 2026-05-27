import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import SecurityPage, { metadata } from "./page";

describe("Security public page", () => {
  it("renders security and trust sections with route CTAs", () => {
    render(<SecurityPage />);

    expect(
      screen.getByRole("heading", {
        name: "Security-first document AI for trusted enterprise knowledge",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Core security pillars" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Document handling lifecycle" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Access, session safety, and governance",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Compliance readiness with careful claims",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Data retention and deletion posture",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Security FAQ" }),
    ).toBeInTheDocument();

    expect(
      screen.getByRole("link", { name: "Request Security Review" }),
    ).toHaveAttribute("href", "/contact");
    expect(
      screen.getByRole("link", { name: "Review Architecture" }),
    ).toHaveAttribute("href", "/documents");
    expect(
      screen.getAllByRole("link", { name: "Talk to Security" })[0],
    ).toHaveAttribute("href", "/contact");
    expect(
      screen.getAllByRole("link", { name: "Request Demo" }).length,
    ).toBeGreaterThanOrEqual(1);
  });

  it("defines unique SEO metadata for /security", () => {
    expect(metadata.title).toBe("Security & Trust | Rudix");
    expect(metadata.description).toBe(
      "Learn how Rudix approaches document privacy, organization isolation, access controls, auditability, and secure AI document workflows.",
    );
    expect(metadata.alternates?.canonical).toBe("/security");
  });
});
