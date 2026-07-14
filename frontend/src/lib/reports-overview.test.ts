import { describe, expect, it } from "vitest";
import {
  buildRecommendedActions,
  calculateOverviewKpis,
  reportDateRange,
  type ReportsOverviewData,
} from "@/lib/reports-overview";

const data = {
  usage: {
    totals: { questions_asked: 90, active_users: 12, failed_indexing_jobs: 2 },
  },
  analytics: { total_queries: 100, low_confidence_queries: 9 },
  trust: {
    trust_distribution: { high_count: 72, low_count: 8 },
    warnings: {
      citation_validation_failed_count: 4,
      stale_source_count: 3,
      ocr_count: 2,
      extraction_count: 1,
      processing_count: 1,
    },
  },
  failedJobs: { total: 5 },
  conflicts: { total: 3 },
  trends: null,
  gaps: null,
  unavailable: [],
} as unknown as ReportsOverviewData;

describe("reports overview calculations", () => {
  it("calculates every KPI from its authoritative source", () => {
    expect(calculateOverviewKpis(data)).toEqual({
      questions: 100,
      trustedAnswers: 72,
      lowConfidence: 9,
      citationIssues: 4,
      sourcesNeedingReview: 7,
      activeUsers: 12,
      failedIndexingJobs: 5,
      permissionConflicts: 3,
    });
  });

  it("builds prioritized, actionable recommendations", () => {
    const actions = buildRecommendedActions(calculateOverviewKpis(data));
    expect(actions.map((action) => action.title)).toEqual([
      "Resolve permission conflicts",
      "Retry failed indexing jobs",
      "Review citation issues",
      "Refresh unhealthy sources",
    ]);
    expect(actions[0]).toMatchObject({
      priority: "High",
      href: "/reports/permissions-access",
    });
  });

  it("converts date presets to stable inclusive API ranges", () => {
    expect(reportDateRange("7d", new Date("2026-07-13T12:00:00Z"))).toEqual({
      from: "2026-07-07",
      to: "2026-07-13",
    });
    expect(reportDateRange("all")).toEqual({});
  });
});
