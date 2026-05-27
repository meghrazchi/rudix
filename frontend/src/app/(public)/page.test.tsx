import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import Home from "./page";

const originalEnv = { ...process.env };

describe("Public Landing Page", () => {
  beforeEach(() => {
    process.env = { ...originalEnv };
    delete process.env.NEXT_PUBLIC_PUBLIC_PRODUCT_URL;
    delete process.env.NEXT_PUBLIC_PUBLIC_SOLUTIONS_URL;
    delete process.env.NEXT_PUBLIC_PUBLIC_SECURITY_URL;
    delete process.env.NEXT_PUBLIC_PUBLIC_PRICING_URL;
    delete process.env.NEXT_PUBLIC_PUBLIC_DOCS_URL;
    delete process.env.NEXT_PUBLIC_PUBLIC_TRIAL_URL;
    delete process.env.NEXT_PUBLIC_PUBLIC_DEMO_URL;
    delete process.env.NEXT_PUBLIC_PUBLIC_STATUS_URL;
    delete process.env.NEXT_PUBLIC_PUBLIC_CONTACT_URL;
    delete process.env.NEXT_PUBLIC_PUBLIC_LOGIN_URL;
    delete process.env.NEXT_PUBLIC_HELP_DOCS_URL;
    delete process.env.NEXT_PUBLIC_SUPPORT_URL;
  });

  afterEach(() => {
    process.env = { ...originalEnv };
  });

  it("renders all major landing sections", () => {
    render(<Home />);

    expect(
      screen.getByRole("link", { name: /Skip to main content/i }),
    ).toBeInTheDocument();

    expect(
      screen.getByRole("heading", { name: /Ask your documents/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: /Your team has the answers\. They are just buried\./i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Upload. Ask. Verify." }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Built for every team." }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Designed for private document workflows.",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Ready to turn your documents into an AI assistant?",
      }),
    ).toBeInTheDocument();

    expect(
      screen.getAllByRole("link", { name: "Login" }).length,
    ).toBeGreaterThanOrEqual(1);
    expect(
      screen.getAllByRole("link", { name: "Speak to us" }).length,
    ).toBeGreaterThanOrEqual(1);
    expect(
      screen.getByRole("link", { name: "Try the demo" }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("link", { name: "View documentation" }).length,
    ).toBeGreaterThanOrEqual(1);
  });

  it("uses shared default routes when public env links are not configured", () => {
    render(<Home />);

    expect(screen.getAllByRole("link", { name: "Product" })[0]).toHaveAttribute(
      "href",
      "/product",
    );
    expect(
      screen.getAllByRole("link", { name: "Solutions" })[0],
    ).toHaveAttribute("href", "/solutions");
    expect(
      screen.getAllByRole("link", { name: "Security" })[0],
    ).toHaveAttribute("href", "/security");
    expect(screen.getAllByRole("link", { name: "Pricing" })[0]).toHaveAttribute(
      "href",
      "/pricing",
    );
    expect(screen.getByRole("link", { name: "Try the demo" })).toHaveAttribute(
      "href",
      "/signup",
    );
    expect(
      screen.getAllByRole("link", { name: "Speak to us" })[0],
    ).toHaveAttribute("href", "/contact");
    expect(
      screen.getAllByRole("link", { name: "View documentation" })[0],
    ).toHaveAttribute("href", "/documents");
  });

  it("applies env-driven public links when configured", () => {
    process.env.NEXT_PUBLIC_PUBLIC_PRODUCT_URL = "/product-overview";
    process.env.NEXT_PUBLIC_PUBLIC_SOLUTIONS_URL = "/solutions-overview";
    process.env.NEXT_PUBLIC_PUBLIC_SECURITY_URL = "/security-overview";
    process.env.NEXT_PUBLIC_PUBLIC_PRICING_URL = "/pricing-overview";
    process.env.NEXT_PUBLIC_PUBLIC_TRIAL_URL = "https://trial.example.com";
    process.env.NEXT_PUBLIC_PUBLIC_DEMO_URL = "https://demo.example.com";
    process.env.NEXT_PUBLIC_PUBLIC_DOCS_URL = "https://docs.example.com";

    render(<Home />);

    expect(screen.getAllByRole("link", { name: "Product" })[0]).toHaveAttribute(
      "href",
      "/product-overview",
    );
    expect(
      screen.getAllByRole("link", { name: "Solutions" })[0],
    ).toHaveAttribute("href", "/solutions-overview");
    expect(
      screen.getAllByRole("link", { name: "Security" })[0],
    ).toHaveAttribute("href", "/security-overview");
    expect(screen.getAllByRole("link", { name: "Pricing" })[0]).toHaveAttribute(
      "href",
      "/pricing-overview",
    );
    expect(screen.getByRole("link", { name: "Try the demo" })).toHaveAttribute(
      "href",
      "https://trial.example.com",
    );
    expect(
      screen.getAllByRole("link", { name: "Speak to us" })[0],
    ).toHaveAttribute("href", "https://demo.example.com");
    expect(
      screen.getAllByRole("link", { name: "View documentation" })[0],
    ).toHaveAttribute("href", "https://docs.example.com");
  });
});
