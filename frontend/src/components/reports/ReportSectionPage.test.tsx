import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ReportSectionPage } from "@/components/reports/ReportSectionPage";

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: {
      status: "authenticated",
      session: { role: "owner", organizationId: "org-1", userId: "user-1" },
    },
  }),
}));

vi.mock("@/components/reports/ReportsOverviewDashboard", () => ({
  ReportsOverviewDashboard: () => <h1>Reports overview</h1>,
}));

vi.mock("@/components/reports/ReportBackendData", () => ({
  ReportBackendDataProvider: ({ children }: { children: React.ReactNode }) =>
    children,
  useReportBackendData: () => ({
    usage: {
      totals: {},
      series: [],
      feature_area_breakdown: {},
      top_users: [],
    },
    analytics: null,
    trust: { trust_distribution: {}, warnings: {}, daily_trends: [] },
    failedJobs: { total: 0, items: [] },
    conflicts: { total: 0, items: [] },
    gaps: { total: 0, items: [] },
    feedbackMetrics: { period_days: 30, total_feedback: 0, categories: [] },
    feedbackItems: { total: 0, items: [] },
  }),
}));

describe("ReportSectionPage route wiring", () => {
  it.each([
    [undefined, "Reports overview"],
    ["answer-quality", "Answer Quality"],
    ["source-health", "Source Health"],
    ["usage-adoption", "Usage & Adoption"],
    ["permissions-access", "Permissions & Access"],
    ["feedback-issues", "Feedback & Issues"],
    ["knowledge-gaps", "Knowledge Gaps"],
  ])("wires %s to its report dashboard", (slug, heading) => {
    render(<ReportSectionPage slug={slug} />);

    expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
  });
});
