import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ContactPage, { metadata } from "./page";

describe("Contact public page", () => {
  it("renders contact hero, form, and contact resource cards", () => {
    render(<ContactPage />);

    expect(
      screen.getByRole("heading", {
        name: "Speak with us about your document workflow",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Book a demo" }),
    ).toBeInTheDocument();

    expect(screen.getByLabelText("Full name")).toBeInTheDocument();
    expect(screen.getByLabelText("Work email")).toBeInTheDocument();
    expect(screen.getByLabelText("Company")).toBeInTheDocument();
    expect(screen.getByLabelText("Team size")).toBeInTheDocument();
    expect(screen.getByLabelText("Role / title")).toBeInTheDocument();
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

  it("defines unique SEO metadata for /contact", () => {
    expect(metadata.title).toBe("Contact & Demo | Rudix");
    expect(metadata.description).toBe(
      "Request a Rudix demo or contact the team to discuss document AI workflows, governance needs, and rollout planning.",
    );
    expect(metadata.alternates?.canonical).toBe("/contact");
  });
});
