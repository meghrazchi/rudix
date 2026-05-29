import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ResearchSolutionPage } from "@/components/public/pages/ResearchSolutionPage";

const originalEnv = { ...process.env };

function clearPublicEnv() {
  delete process.env.NEXT_PUBLIC_PUBLIC_DEMO_URL;
  delete process.env.NEXT_PUBLIC_PUBLIC_TRIAL_URL;
  delete process.env.NEXT_PUBLIC_PUBLIC_DOCS_URL;
}

describe("Research solution page (/solutions/research)", () => {
  beforeEach(() => {
    process.env = { ...originalEnv };
    clearPublicEnv();
  });

  afterEach(() => {
    process.env = { ...originalEnv };
  });

  it("renders the hero with research-specific headline and badge", () => {
    render(<ResearchSolutionPage />);

    expect(
      screen.getByRole("heading", {
        name: "Extract insights from technical PDFs and reports.",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Analyst Intelligence")).toBeInTheDocument();
  });

  it("renders the hero image and both CTAs", () => {
    render(<ResearchSolutionPage />);

    expect(
      screen.getByAltText(
        "Enterprise research analyst dashboard showing data visualizations and document insights",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Request Demo/i })).toHaveAttribute(
      "href",
      "/contact",
    );
    expect(
      screen.getByRole("link", { name: "View Documentation" }),
    ).toHaveAttribute("href", "/documents");
  });

  it("renders the problem section with four bento cards", () => {
    render(<ResearchSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "The research friction point." }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Information Overload" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Manual Summarization" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Lack of Citations" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Technical Fragmentation" }),
    ).toBeInTheDocument();
  });

  it("renders document sources section with five research document types", () => {
    render(<ResearchSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "Ingest everything. Analyze anything." }),
    ).toBeInTheDocument();
    expect(screen.getByText("Whitepapers")).toBeInTheDocument();
    expect(screen.getByText("Market Research")).toBeInTheDocument();
    expect(screen.getByText("Analyst Reports")).toBeInTheDocument();
    expect(screen.getByText("Technical Papers")).toBeInTheDocument();
    expect(screen.getByText("Strategy Docs")).toBeInTheDocument();
  });

  it("renders the pipeline section with three numbered steps", () => {
    render(<ResearchSolutionPage />);

    expect(
      screen.getByRole("heading", {
        name: "The High-Fidelity Retrieval Pipeline",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Semantic Chunking" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Vector Indexing" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Verifiable Generation" }),
    ).toBeInTheDocument();
  });

  it("renders the pipeline latency and accuracy metrics", () => {
    render(<ResearchSolutionPage />);

    expect(screen.getByText("124ms")).toBeInTheDocument();
    expect(screen.getByText("99.8%")).toBeInTheDocument();
  });

  it("renders example queries section with four research questions", () => {
    render(<ResearchSolutionPage />);

    expect(
      screen.getByRole("heading", { name: "Query your corpus." }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("What are the core market projections for 2025?"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Which sources discuss implementation risks?"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "How do these two analyst reports differ on cloud adoption?",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Which papers mention the term 'model drift'?"),
    ).toBeInTheDocument();
  });

  it("renders the final CTA section with trial and demo links", () => {
    render(<ResearchSolutionPage />);

    expect(
      screen.getByRole("heading", {
        name: "Ready to upgrade your research infrastructure?",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Get Started Now" }),
    ).toHaveAttribute("href", "/signup");
    expect(
      screen.getByRole("link", { name: "Book Sales Call" }),
    ).toHaveAttribute("href", "/contact");
  });

  it("applies env-driven demo URL to hero CTA when configured", () => {
    process.env.NEXT_PUBLIC_PUBLIC_DEMO_URL = "https://demo.example.com";

    render(<ResearchSolutionPage />);

    expect(screen.getByRole("link", { name: /Request Demo/i })).toHaveAttribute(
      "href",
      "https://demo.example.com",
    );
  });

  it("applies env-driven trial URL to final CTA when configured", () => {
    process.env.NEXT_PUBLIC_PUBLIC_TRIAL_URL = "https://trial.example.com";

    render(<ResearchSolutionPage />);

    expect(
      screen.getByRole("link", { name: "Get Started Now" }),
    ).toHaveAttribute("href", "https://trial.example.com");
  });

  it("renders breadcrumb navigation back to solutions", () => {
    render(<ResearchSolutionPage />);

    expect(screen.getByRole("link", { name: "Solutions" })).toHaveAttribute(
      "href",
      "/solutions",
    );
    expect(screen.getByText("Research")).toBeInTheDocument();
  });
});
