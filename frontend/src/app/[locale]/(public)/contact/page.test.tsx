import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ContactPage, { generateMetadata } from "./page";

describe("Contact public page", () => {
  it("renders contact hero, form, and contact resource cards", () => {
    render(<ContactPage />);

    expect(
      screen.getByRole("heading", {
        name: "Speak with us about your document workflow",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Request a Demo" }),
    ).toBeInTheDocument();

    expect(
      screen.getByLabelText(/First name\s+Last name/i),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Work email")).toBeInTheDocument();
    expect(screen.getByLabelText("Company name")).toBeInTheDocument();
    expect(screen.getByLabelText("Team size")).toBeInTheDocument();
    expect(screen.getByLabelText("Your role")).toBeInTheDocument();
    expect(screen.getByLabelText("Primary use case")).toBeInTheDocument();
    expect(screen.getByLabelText("Message")).toBeInTheDocument();

    expect(
      screen.getByRole("heading", { name: "Good fit for teams that need" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sales" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Support" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Security review" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Status and docs" }),
    ).toBeInTheDocument();

    expect(
      screen.getByRole("heading", { name: "Contact and demo FAQ" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Need a live walkthrough?" }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("link", { name: "Request Demo" }).length,
    ).toBeGreaterThanOrEqual(1);
  });

  it("defines localized SEO metadata for /contact", async () => {
    const metadata = await generateMetadata({
      params: Promise.resolve({ locale: "fr" }),
    });

    expect(metadata.title).toBe("Contact et démo | Rudix");
    expect(metadata.alternates?.canonical).toContain("/fr/contact");
  });
});
