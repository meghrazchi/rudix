import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AcceptableUsePage from "./page";

describe("Acceptable Use Policy page", () => {
  it("renders the page heading", () => {
    render(<AcceptableUsePage />);
    expect(
      screen.getByRole("heading", { name: /acceptable use policy/i, level: 1 }),
    ).toBeInTheDocument();
  });

  it("shows the legal review notice", () => {
    render(<AcceptableUsePage />);
    expect(screen.getByRole("note")).toHaveTextContent(
      /pending.*legal review/i,
    );
  });

  it("shows version and effective date metadata", () => {
    render(<AcceptableUsePage />);
    expect(screen.getByText(/version 0\.1/i)).toBeInTheDocument();
    expect(screen.getByText(/effective/i)).toBeInTheDocument();
  });

  it("renders permitted and prohibited use sections", () => {
    render(<AcceptableUsePage />);
    expect(
      screen.getByRole("region", { name: /permitted uses/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: /prohibited uses/i }),
    ).toBeInTheDocument();
  });

  it("links to the security disclosure policy", () => {
    render(<AcceptableUsePage />);
    expect(
      screen.getByRole("link", { name: /security disclosure policy/i }),
    ).toHaveAttribute("href", "/legal/security-disclosure");
  });

  it("renders the public header and footer", () => {
    render(<AcceptableUsePage />);
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
  });
});
