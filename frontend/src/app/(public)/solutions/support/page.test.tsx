import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { SupportSolutionPage } from "@/components/public/pages/SupportSolutionPage";

const originalEnv = { ...process.env };

function clearPublicEnv() {
  delete process.env.NEXT_PUBLIC_PUBLIC_DEMO_URL;
  delete process.env.NEXT_PUBLIC_PUBLIC_TRIAL_URL;
  delete process.env.NEXT_PUBLIC_PUBLIC_CONTACT_URL;
}

describe("Support solution page (/solutions/support)", () => {
  beforeEach(() => {
    process.env = { ...originalEnv };
    clearPublicEnv();
  });

  afterEach(() => {
    process.env = { ...originalEnv };
  });

  it("renders the hero with support-specific headline and badge", () => {
    render(<SupportSolutionPage />);

    expect(
      screen.getByRole("heading", {
        name: "Help support agents answer faster.",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Support Solutions")).toBeInTheDocument();
  });

  it("renders the problem section with three pain-point cards", () => {
    render(<SupportSolutionPage />);

    expect(
      screen.getByRole("heading", { name: /Support knowledge is often scattered/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Tool Fatigue" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Slow Onboarding" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Inconsistent Data" })).toBeInTheDocument();
  });

  it("renders document sources section with six source cards", () => {
    render(<SupportSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "Connect all your support assets." }),
    ).toBeInTheDocument();
    expect(screen.getByText("Product Documentation")).toBeInTheDocument();
    expect(screen.getByText("Troubleshooting Guides")).toBeInTheDocument();
    expect(screen.getByText("Release Notes")).toBeInTheDocument();
    expect(screen.getByText("Known Issue Lists")).toBeInTheDocument();
    expect(screen.getByText("Escalation Runbooks")).toBeInTheDocument();
  });

  it("renders how it works section with four steps", () => {
    render(<SupportSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "How it works" }),
    ).toBeInTheDocument();
    expect(screen.getByText("1. Upload")).toBeInTheDocument();
    expect(screen.getByText("2. Index")).toBeInTheDocument();
    expect(screen.getByText("3. Ask")).toBeInTheDocument();
    expect(screen.getByText("4. Resolve")).toBeInTheDocument();
  });

  it("renders example queries section with active query and smaller cards", () => {
    render(<SupportSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "Precision retrieval in action." }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/troubleshoot login failures for users on Enterprise Plan/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /"Which plan includes SSO\?"/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /"What changed in the latest release\?"/ }),
    ).toBeInTheDocument();
  });

  it("renders the final CTA section", () => {
    render(<SupportSolutionPage />);

    expect(
      screen.getByRole("heading", {
        name: "Give your support team a document-backed copilot.",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Get Started" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Request a Demo" }),
    ).toBeInTheDocument();
  });

  it("renders hero CTA links pointing to demo and contact", () => {
    render(<SupportSolutionPage />);

    const speakLinks = screen.getAllByRole("link", { name: "Speak to us about support" });
    expect(speakLinks.length).toBeGreaterThanOrEqual(1);
    speakLinks.forEach((link) => expect(link).toHaveAttribute("href", "/contact"));
  });

  it("applies env-driven demo URL when configured", () => {
    process.env.NEXT_PUBLIC_PUBLIC_DEMO_URL = "https://demo.example.com";

    render(<SupportSolutionPage />);

    const speakLinks = screen.getAllByRole("link", { name: "Speak to us about support" });
    speakLinks.forEach((link) =>
      expect(link).toHaveAttribute("href", "https://demo.example.com"),
    );
  });

  it("renders breadcrumb navigation back to solutions", () => {
    render(<SupportSolutionPage />);

    expect(screen.getByRole("link", { name: "Solutions" })).toHaveAttribute(
      "href",
      "/solutions",
    );
    expect(screen.getByText("Support")).toBeInTheDocument();
  });
});
