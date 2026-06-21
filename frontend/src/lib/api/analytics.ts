import { apiRequest } from "@/lib/api/request";

export type AnalyticsDateRange = {
  from: string;
  to: string;
};

export type AnalyticsActivationSummary = {
  signup_completed: number;
  organization_created: number;
  first_upload: number;
  first_indexed_document: number;
  first_question: number;
  first_cited_answer: number;
  funnel_completion_rate: number | null;
};

export type AnalyticsSummaryResponse = {
  organization_id: string;
  range: AnalyticsDateRange;
  generated_at: string;
  enabled: boolean;
  disabled_reason: string | null;
  total_events: number;
  active_users: number;
  activation: AnalyticsActivationSummary;
  feature_usage: Record<string, number>;
  page_usage: Record<string, number>;
  event_counts: Record<string, number>;
};

export type AnalyticsSummaryQuery = {
  from?: string;
  to?: string;
};

export async function getAnalyticsSummary(
  query: AnalyticsSummaryQuery = {},
): Promise<AnalyticsSummaryResponse> {
  return apiRequest<AnalyticsSummaryResponse>("/analytics/summary", {
    query,
  });
}
