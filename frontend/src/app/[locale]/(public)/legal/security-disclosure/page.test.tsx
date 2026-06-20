import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import SecurityDisclosureRoute from "./page";

describe("Security Disclosure Policy page", () => {
  it("renders the page heading", () => {
    render(<SecurityDisclosureRoute />);
    expect(
      screen.getByRole("heading", {
        name: /security disclosure policy/i,
        level: 1,
      }),
    ).toBeInTheDocument();
  });

  it("shows the legal review notice", () => {
    render(<SecurityDisclosureRoute />);
    expect(screen.getByRole("note")).toHaveTextContent(
      /pending.*legal review/i,
    );
  });

  it("shows version and effective date metadata", () => {
    render(<SecurityDisclosureRoute />);
    expect(screen.getByText(/version 0\.1/i)).toBeInTheDocument();
    expect(screen.getByText(/effective/i)).toBeInTheDocument();
  });

  it("renders key disclosure policy sections", () => {
    render(<SecurityDisclosureRoute />);
    expect(
      screen.getByRole("region", { name: /how to report/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: /in-scope/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: /out of scope/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: /our response/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", {
        name: /responsible disclosure guidelines/i,
      }),
    ).toBeInTheDocument();
  });

  it("provides a security contact email link", () => {
    render(<SecurityDisclosureRoute />);
    const emailLink = screen.getByRole("link", { name: /security@rudix\.ai/i });
    expect(emailLink).toHaveAttribute("href", "mailto:security@rudix.ai");
  });

  it("renders the public header and footer", () => {
    render(<SecurityDisclosureRoute />);
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
  });
});
