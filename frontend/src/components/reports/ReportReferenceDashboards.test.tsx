import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  AnswerQualityDashboard,
  FeedbackIssuesDashboard,
  SourceHealthDashboard,
} from "@/components/reports/ReportReferenceDashboards";

describe("reference report dashboards", () => {
  it("renders answer quality metrics and query details", () => {
    const { container } = render(<AnswerQualityDashboard />);
    expect(container.querySelector("main")).toHaveClass("gap-6");
    expect(
      container.querySelector('[aria-label="Answer quality key metrics"]'),
    ).toHaveClass("gap-4", "lg:gap-5");
    expect(container.querySelector("article")).toHaveClass("p-4", "sm:p-5");
    expect(
      screen.getByRole("heading", { name: "Answer Quality" }),
    ).toBeInTheDocument();
    expect(screen.getByText("94.2%")).toBeInTheDocument();
    expect(
      container.querySelector('[data-chart-library="recharts"]'),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", {
        name: "How do I reset my SSO credentials?",
      }),
    );
    expect(
      screen.getByRole("dialog", { name: "Query Details" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Guardrail validation passed")).toBeInTheDocument();
  });

  it("renders source health recommendations and integrity table", () => {
    const { container } = render(<SourceHealthDashboard />);
    expect(
      screen.getByRole("heading", { name: "Source Health" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Retrieval Volatility" }),
    ).toBeInTheDocument();
    expect(
      container.querySelector('[data-chart-library="recharts"]'),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("table", { name: "Source citation integrity" }),
    ).toBeInTheDocument();
  });

  it("renders feedback categories and queue", () => {
    const { container } = render(<FeedbackIssuesDashboard />);
    expect(
      screen.getByRole("heading", { name: "Feedback & Issues" }),
    ).toBeInTheDocument();
    expect(
      container.querySelector('[data-chart-library="recharts"]'),
    ).toHaveAttribute(
      "aria-label",
      expect.stringContaining("Wrong answer: 42%"),
    );
    expect(
      screen.getByRole("table", { name: "Feedback queue" }),
    ).toBeInTheDocument();
  });
});
