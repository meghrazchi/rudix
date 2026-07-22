import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  AnswerQualityDashboard,
  FeedbackIssuesDashboard,
  SourceHealthDashboard,
} from "@/components/reports/ReportReferenceDashboards";

vi.mock("@/components/reports/ReportBackendData", () => ({
  useReportBackendData: () => ({
    usage: { totals: { questions_asked: 20 } },
    analytics: { low_confidence_queries: 3 },
    trust: {
      total_answers: 20,
      avg_confidence_score: 0.89,
      avg_citation_support_score: 0.942,
      avg_verification_support_score: 0.91,
      trust_distribution: { high_count: 17, low_count: 3 },
      warnings: {
        citation_validation_failed_count: 2,
        stale_source_count: 1,
        extraction_count: 0,
      },
      daily_trends: [
        {
          date: "2026-07-20",
          answer_count: 20,
          not_found_count: 1,
          avg_confidence_score: 0.89,
          avg_citation_support_score: 0.942,
        },
      ],
    },
    failedJobs: {
      total: 1,
      items: [
        {
          id: "job-1",
          task_name: "index_document",
          job_type: "indexing",
          attempt_count: 2,
          queue_name: "documents",
          status: "failed",
          is_retryable: true,
        },
      ],
    },
    feedbackMetrics: {
      period_days: 30,
      total_feedback: 42,
      categories: [{ category: "wrong answer", count: 42 }],
    },
    feedbackItems: { total: 0, items: [] },
  }),
}));

describe("reference report dashboards", () => {
  it("renders backend answer quality metrics", () => {
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
    expect(
      screen.getByRole("table", { name: "Daily quality analysis" }),
    ).toBeInTheDocument();
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
      screen.getByRole("table", { name: "Source processing health" }),
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
      expect.stringContaining("wrong answer: 42%"),
    );
    expect(
      screen.getByRole("table", { name: "Feedback queue" }),
    ).toBeInTheDocument();
  });
});
