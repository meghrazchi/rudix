import {
  getUsageDashboard,
  type UsageDashboardResponse,
} from "@/lib/api/admin-usage";
import { listConflicts, type ConflictListResponse } from "@/lib/api/conflicts";
import {
  listFailedJobs,
  type FailedJobsListResponse,
} from "@/lib/api/failed-jobs";
import {
  getQueryAnalyticsSummary,
  getQueryAnalyticsTrends,
  listKnowledgeGaps,
  type KnowledgeGapListResponse,
  type QueryAnalyticsSummaryResponse,
  type QueryTrendsResponse,
} from "@/lib/api/query-analytics";
import {
  getTrustAnalytics,
  type TrustAnalyticsResponse,
} from "@/lib/api/trust_analytics";
import {
  getFeedbackMetrics,
  type FeedbackMetricsResponse,
} from "@/lib/api/feedback";
import {
  listFeedbackReviewItems,
  type FeedbackReviewListResponse,
} from "@/lib/api/feedback-review";
import type { ReportFilters } from "@/lib/reports";

export type ReportsOverviewData = {
  usage: UsageDashboardResponse | null;
  analytics: QueryAnalyticsSummaryResponse | null;
  trends: QueryTrendsResponse | null;
  trust: TrustAnalyticsResponse | null;
  failedJobs: FailedJobsListResponse | null;
  conflicts: ConflictListResponse | null;
  gaps: KnowledgeGapListResponse | null;
  feedbackMetrics: FeedbackMetricsResponse | null;
  feedbackItems: FeedbackReviewListResponse | null;
  unavailable: string[];
};

export type ReportsOverviewKpis = {
  questions: number;
  trustedAnswers: number;
  lowConfidence: number;
  citationIssues: number;
  sourcesNeedingReview: number;
  activeUsers: number;
  failedIndexingJobs: number;
  permissionConflicts: number;
};

export type OverviewAction = {
  id: "permissions" | "indexing" | "citations" | "sources";
  count: number;
  priority: "High" | "Medium" | "Low";
  href: string;
};

export function calculateOverviewKpis(
  data: ReportsOverviewData,
): ReportsOverviewKpis {
  const trust = data.trust;
  return {
    questions:
      data.analytics?.total_queries ?? data.usage?.totals.questions_asked ?? 0,
    trustedAnswers: trust?.trust_distribution.high_count ?? 0,
    lowConfidence:
      data.analytics?.low_confidence_queries ??
      trust?.trust_distribution.low_count ??
      0,
    citationIssues: trust?.warnings.citation_validation_failed_count ?? 0,
    sourcesNeedingReview: trust
      ? trust.warnings.stale_source_count +
        trust.warnings.ocr_count +
        trust.warnings.extraction_count +
        trust.warnings.processing_count
      : 0,
    activeUsers: data.usage?.totals.active_users ?? 0,
    failedIndexingJobs:
      data.failedJobs?.total ?? data.usage?.totals.failed_indexing_jobs ?? 0,
    permissionConflicts: data.conflicts?.total ?? 0,
  };
}

export function buildRecommendedActions(
  kpis: ReportsOverviewKpis,
): OverviewAction[] {
  const actions: OverviewAction[] = [];
  if (kpis.permissionConflicts > 0)
    actions.push({
      id: "permissions",
      count: kpis.permissionConflicts,
      priority: "High",
      href: "/reports/permissions-access",
    });
  if (kpis.failedIndexingJobs > 0)
    actions.push({
      id: "indexing",
      count: kpis.failedIndexingJobs,
      priority: "High",
      href: "/reports/source-health",
    });
  if (kpis.citationIssues > 0)
    actions.push({
      id: "citations",
      count: kpis.citationIssues,
      priority: "Medium",
      href: "/reports/answer-quality",
    });
  if (kpis.sourcesNeedingReview > 0)
    actions.push({
      id: "sources",
      count: kpis.sourcesNeedingReview,
      priority: "Medium",
      href: "/reports/source-health",
    });
  return actions.slice(0, 4);
}

export function reportDateRange(
  date: string,
  now = new Date(),
): { from?: string; to?: string } {
  if (date === "all") return {};
  const days = Number.parseInt(date, 10);
  if (!Number.isFinite(days)) return {};
  const from = new Date(now);
  from.setUTCDate(from.getUTCDate() - days + 1);
  return {
    from: from.toISOString().slice(0, 10),
    to: now.toISOString().slice(0, 10),
  };
}

export async function getReportsOverview(
  filters: ReportFilters,
): Promise<ReportsOverviewData> {
  const range = reportDateRange(filters.date);
  const calls = [
    getUsageDashboard({
      ...range,
      model: filters.model === "all" ? undefined : filters.model,
    }),
    getQueryAnalyticsSummary(range),
    getQueryAnalyticsTrends(range),
    getTrustAnalytics(range),
    listFailedJobs({ status: "failed", page_size: 1 }),
    listConflicts({ status: "open", page_size: 100 }),
    listKnowledgeGaps({ status: "open", limit: 5 }),
    getFeedbackMetrics(Number.parseInt(filters.date, 10) || 30),
    listFeedbackReviewItems({ limit: 20, offset: 0 }),
  ] as const;
  const results = await Promise.allSettled(calls);
  const names = [
    "usage",
    "answerAnalytics",
    "trends",
    "trust",
    "indexing",
    "permissions",
    "knowledgeGaps",
    "feedbackMetrics",
    "feedbackQueue",
  ];
  const value = <T>(index: number): T | null =>
    results[index]?.status === "fulfilled" ? (results[index].value as T) : null;
  return {
    usage: value(0),
    analytics: value(1),
    trends: value(2),
    trust: value(3),
    failedJobs: value(4),
    conflicts: value(5),
    gaps: value(6),
    feedbackMetrics: value(7),
    feedbackItems: value(8),
    unavailable: names.filter(
      (_, index) => results[index]?.status === "rejected",
    ),
  };
}
