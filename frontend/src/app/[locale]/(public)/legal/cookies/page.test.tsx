import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CookiesPage from "./page";

describe("Cookie Policy page", () => {
  it("renders the page heading", () => {
    render(<CookiesPage />);
    expect(
      screen.getByRole("heading", { name: /cookie policy/i, level: 1 }),
    ).toBeInTheDocument();
  });

  it("shows the legal review notice", () => {
    render(<CookiesPage />);
    expect(screen.getByRole("note")).toHaveTextContent(
      /pending.*legal review/i,
    );
  });

  it("shows version and effective date metadata", () => {
    render(<CookiesPage />);
    expect(screen.getByText(/version 0\.1/i)).toBeInTheDocument();
    expect(screen.getByText(/effective/i)).toBeInTheDocument();
  });

  it("renders key cookie policy sections", () => {
    render(<CookiesPage />);
    expect(
      screen.getByRole("region", { name: /cookies we use/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: /what we do not use/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: /how to control cookies/i }),
    ).toBeInTheDocument();
  });

  it("describes session cookie", () => {
    render(<CookiesPage />);
    expect(screen.getByText(/session cookie/i)).toBeInTheDocument();
  });

  it("states no third-party tracking cookies are used", () => {
    render(<CookiesPage />);
    const noTracking = screen.getByRole("region", {
      name: /what we do not use/i,
    });
    expect(noTracking).toHaveTextContent(/third-party advertising cookies/i);
  });

  it("renders the public header and footer", () => {
    render(<CookiesPage />);
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
  });
});
