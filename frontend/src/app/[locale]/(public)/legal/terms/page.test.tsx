import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import TermsPage from "./page";

describe("Terms of Service page", () => {
  it("renders the page heading", () => {
    render(<TermsPage />);
    expect(
      screen.getByRole("heading", { name: /terms of service/i, level: 1 }),
    ).toBeInTheDocument();
  });

  it("shows the legal review notice", () => {
    render(<TermsPage />);
    expect(screen.getByRole("note")).toHaveTextContent(
      /pending.*legal review/i,
    );
  });

  it("shows version and effective date metadata", () => {
    render(<TermsPage />);
    expect(screen.getByText(/version 0\.1/i)).toBeInTheDocument();
    expect(screen.getByText(/effective/i)).toBeInTheDocument();
  });

  it("renders key terms sections", () => {
    render(<TermsPage />);
    expect(
      screen.getByRole("region", { name: /acceptance/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: /permitted use/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: /restrictions/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: /your content/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: /termination/i }),
    ).toBeInTheDocument();
  });

  it("links to the acceptable use policy", () => {
    render(<TermsPage />);
    expect(
      screen.getByRole("link", { name: /acceptable use policy/i }),
    ).toHaveAttribute("href", "/legal/acceptable-use");
  });

  it("renders the public header and footer", () => {
    render(<TermsPage />);
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
  });
});
