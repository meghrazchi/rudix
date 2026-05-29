import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { OperationsSolutionPage } from "@/components/public/pages/OperationsSolutionPage";

const originalEnv = { ...process.env };

function clearPublicEnv() {
  delete process.env.NEXT_PUBLIC_PUBLIC_DEMO_URL;
  delete process.env.NEXT_PUBLIC_PUBLIC_DOCS_URL;
}

describe("Operations solution page (/solutions/operations)", () => {
  beforeEach(() => {
    process.env = { ...originalEnv };
    clearPublicEnv();
  });

  afterEach(() => {
    process.env = { ...originalEnv };
  });

  it("renders the hero with operations-specific headline and badge", () => {
    render(<OperationsSolutionPage />);

    expect(
      screen.getByRole("heading", {
        name: "Runbook answers when your team needs them.",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Operations & Incident Response")).toBeInTheDocument();
  });

  it("renders the hero CTAs for demo and documentation", () => {
    render(<OperationsSolutionPage />);

    const demoLinks = screen.getAllByRole("link", { name: "Speak to us about operations" });
    expect(demoLinks.length).toBeGreaterThanOrEqual(1);
    demoLinks.forEach((l) => expect(l).toHaveAttribute("href", "/contact"));
    expect(
      screen.getByRole("link", { name: "View documentation" }),
    ).toHaveAttribute("href", "/documents");
  });

  it("renders the problem section with three bento cards", () => {
    render(<OperationsSolutionPage />);

    expect(
      screen.getByRole("heading", {
        name: /During incidents, searching documents wastes time/i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Runbooks scattered across wikis" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Incident steps need to be followed quickly",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Outdated procedures create risk" }),
    ).toBeInTheDocument();
  });

  it("renders the problem section image with descriptive alt text", () => {
    render(<OperationsSolutionPage />);

    expect(
      screen.getByAltText(
        "Code terminal showing operations runbook and incident response procedures",
      ),
    ).toBeInTheDocument();
  });

  it("renders document sources section with six operational document types", () => {
    render(<OperationsSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "Universal technical ingestion." }),
    ).toBeInTheDocument();
    expect(screen.getByText("Incident response runbooks")).toBeInTheDocument();
    expect(screen.getByText("SOPs")).toBeInTheDocument();
    expect(screen.getByText("Troubleshooting guides")).toBeInTheDocument();
    expect(screen.getByText("Deployment procedures")).toBeInTheDocument();
    expect(screen.getByText("Escalation policies")).toBeInTheDocument();
    expect(screen.getByText("System recovery guides")).toBeInTheDocument();
  });

  it("renders the four-step how it works section", () => {
    render(<OperationsSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "How Rudix secures your uptime." }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Upload" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Index" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Ask" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Solve" })).toBeInTheDocument();
  });

  it("renders example queries section with three question chips", () => {
    render(<OperationsSolutionPage />);

    expect(
      screen.getByRole("heading", {
        name: "Built for the high-pressure query.",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/"What are the steps for a priority incident\?"/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/"How do we restart the failed indexing worker\?"/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/"Who needs to be notified during an outage\?"/),
    ).toBeInTheDocument();
  });

  it("renders the chat mockup with cited SOP answer", () => {
    render(<OperationsSolutionPage />);

    expect(
      screen.getByText(/Infrastructure Recovery SOP \(v2\.4\)/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/kubectl rollout restart deployment\/indexing-worker/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Infrastructure_SOP_v2\.4\.pdf/i),
    ).toBeInTheDocument();
  });

  it("renders the final CTA section with two action links", () => {
    render(<OperationsSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "Make runbooks easier to use." }),
    ).toBeInTheDocument();
    const speakLinks = screen.getAllByRole("link", {
      name: "Speak to us about operations",
    });
    expect(speakLinks.length).toBeGreaterThanOrEqual(1);
    expect(
      screen.getByRole("link", { name: "Book a Live Demo" }),
    ).toBeInTheDocument();
  });

  it("applies env-driven demo URL when configured", () => {
    process.env.NEXT_PUBLIC_PUBLIC_DEMO_URL = "https://demo.example.com";

    render(<OperationsSolutionPage />);

    const demoLinks = screen.getAllByRole("link", {
      name: "Speak to us about operations",
    });
    demoLinks.forEach((l) =>
      expect(l).toHaveAttribute("href", "https://demo.example.com"),
    );
  });

  it("renders breadcrumb navigation back to solutions", () => {
    render(<OperationsSolutionPage />);

    expect(screen.getByRole("link", { name: "Solutions" })).toHaveAttribute(
      "href",
      "/solutions",
    );
    expect(screen.getByText("Operations")).toBeInTheDocument();
  });
});
