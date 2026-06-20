import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import DpaPage from "./page";

describe("Data Processing Addendum page", () => {
  it("renders the page heading", () => {
    render(<DpaPage />);
    expect(
      screen.getByRole("heading", {
        name: /data processing addendum/i,
        level: 1,
      }),
    ).toBeInTheDocument();
  });

  it("shows the legal review notice", () => {
    render(<DpaPage />);
    expect(screen.getByRole("note")).toHaveTextContent(
      /pending.*legal review/i,
    );
  });

  it("shows version and effective date metadata", () => {
    render(<DpaPage />);
    expect(screen.getByText(/version 0\.1/i)).toBeInTheDocument();
    expect(screen.getByText(/effective/i)).toBeInTheDocument();
  });

  it("renders key DPA sections", () => {
    render(<DpaPage />);
    expect(
      screen.getByRole("region", { name: /scope and purpose/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: /processor obligations/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: /sub-processors/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: /security incident notification/i }),
    ).toBeInTheDocument();
  });

  it("links to the subprocessors page", () => {
    render(<DpaPage />);
    const subprocessorLinks = screen.getAllByRole("link", {
      name: /subprocessors/i,
    });
    expect(subprocessorLinks.length).toBeGreaterThanOrEqual(1);
    expect(subprocessorLinks[0]).toHaveAttribute(
      "href",
      "/legal/subprocessors",
    );
  });

  it("renders the public header and footer", () => {
    render(<DpaPage />);
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
  });
});
