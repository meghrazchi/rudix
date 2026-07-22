import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReportsOverviewDashboard } from "@/components/reports/ReportsOverviewDashboard";

const mocks = vi.hoisted(() => ({ getReportsOverview: vi.fn() }));
const filters = {
  date: "7d",
  workspace: "all",
  team: "all",
  user: "all",
  collection: "all",
  connector: "all",
  language: "de",
  model: "gpt-5",
  confidence: "low",
};
vi.mock("@/lib/reports-overview", async (importOriginal) => {
  const original =
    await importOriginal<typeof import("@/lib/reports-overview")>();
  return { ...original, getReportsOverview: mocks.getReportsOverview };
});
vi.mock("@/components/reports/ReportFilters", () => ({
  useReportFilters: () => ({
    filters,
  }),
}));

const response = {
  usage: {
    totals: {
      questions_asked: 20,
      active_users: 4,
      documents: 3,
      indexing_jobs: 6,
      failed_indexing_jobs: 1,
    },
    series: [
      { period_start: "2026-07-12", questions_asked: 20, active_users: 4 },
    ],
  },
  analytics: {
    total_queries: 20,
    low_confidence_queries: 3,
    top_feedback_categories: [{ category: "incorrect", count: 2 }],
  },
  trust: {
    trust_distribution: { high_count: 14, medium_count: 3, low_count: 3 },
    warnings: {
      citation_validation_failed_count: 2,
      stale_source_count: 1,
      ocr_count: 0,
      extraction_count: 0,
      processing_count: 0,
    },
  },
  failedJobs: { total: 1 },
  conflicts: { total: 1, items: [{ severity: "blocking" }] },
  gaps: {
    items: [
      { gap_id: "g1", topic_label: "Expense policy", occurrence_count: 4 },
    ],
  },
  trends: null,
  unavailable: [],
};

function renderDashboard() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ReportsOverviewDashboard />
    </QueryClientProvider>,
  );
}

describe("ReportsOverviewDashboard", () => {
  beforeEach(() => mocks.getReportsOverview.mockResolvedValue(response));

  it("renders all KPI links and health charts", async () => {
    renderDashboard();
    await screen.findByRole("heading", { name: "Reports overview" });
    expect(screen.getAllByRole("link", { name: /report/i })).toHaveLength(16);
    expect(
      screen.getByRole("heading", { name: "Answer confidence" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Permission warnings" }),
    ).toBeInTheDocument();
    expect(mocks.getReportsOverview).toHaveBeenCalledWith(filters);
  });

  it("preserves global filters in KPI, chart, and action links", async () => {
    renderDashboard();
    const query = "date=7d&language=de&model=gpt-5&confidence=low";
    expect(
      await screen.findByRole("link", { name: "Open Questions asked report" }),
    ).toHaveAttribute("href", `/reports/usage-adoption?${query}`);
    expect(
      screen.getAllByRole("link", { name: /Open detailed report/ })[0],
    ).toHaveAttribute("href", `/reports/answer-quality?${query}`);
    expect(
      screen.getByRole("link", { name: /Review conflicts/ }),
    ).toHaveAttribute("href", `/reports/permissions-access?${query}`);
  });

  it("renders clear recommended actions with CTAs", async () => {
    renderDashboard();
    expect(
      await screen.findByText("Resolve permission conflicts"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Review conflicts/ }),
    ).toHaveAttribute(
      "href",
      "/reports/permissions-access?date=7d&language=de&model=gpt-5&confidence=low",
    );
    expect(
      screen.getByText("High priority · Restore safe access"),
    ).toBeInTheDocument();
  });

  it("uses responsive KPI and chart layout contracts", async () => {
    const { container } = renderDashboard();
    await waitFor(() =>
      expect(
        container.querySelector('[aria-label="Key performance indicators"]'),
      ).toBeTruthy(),
    );
    expect(
      container.querySelector('[aria-label="Key performance indicators"]'),
    ).toHaveClass("sm:grid-cols-2", "lg:grid-cols-4");
    expect(
      container.querySelector('[aria-label="Workspace health charts"]'),
    ).toHaveClass("md:grid-cols-2", "xl:grid-cols-3");
  });
});
