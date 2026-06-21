import { apiRequest } from "@/lib/api/request";

// ── Shared types ───────────────────────────────────────────────────────────────

export type QueryAnalyticsDateRange = {
  from_date: string;
  to_date: string;
};

// ── Summary ────────────────────────────────────────────────────────────────────

export type FeedbackCategoryCount = {
  category: string;
  count: number;
};

export type QueryAnalyticsSummaryResponse = {
  organization_id: string;
  range: QueryAnalyticsDateRange;
  generated_at: string;
  enabled: boolean;
  disabled_reason: string | null;
  total_queries: number;
  answered_queries: number;
  unanswered_queries: number;
  low_confidence_queries: number;
  negative_feedback_count: number;
  unanswered_rate: number | null;
  avg_confidence: number | null;
  negative_feedback_rate: number | null;
  top_feedback_categories: FeedbackCategoryCount[];
  top_feedback_reasons: FeedbackCategoryCount[];
};

export type QueryAnalyticsSummaryQuery = {
  from?: string;
  to?: string;
};

export async function getQueryAnalyticsSummary(
  query: QueryAnalyticsSummaryQuery = {},
): Promise<QueryAnalyticsSummaryResponse> {
  return apiRequest<QueryAnalyticsSummaryResponse>(
    "/admin/query-analytics/summary",
    { query },
  );
}

// ── Trends ─────────────────────────────────────────────────────────────────────

export type QueryTrendPoint = {
  date: string;
  total_queries: number;
  unanswered: number;
  low_confidence: number;
  negative_feedback: number;
  avg_confidence: number | null;
};

export type QueryTrendsResponse = {
  organization_id: string;
  range: QueryAnalyticsDateRange;
  generated_at: string;
  points: QueryTrendPoint[];
};

export async function getQueryAnalyticsTrends(
  query: QueryAnalyticsSummaryQuery = {},
): Promise<QueryTrendsResponse> {
  return apiRequest<QueryTrendsResponse>("/admin/query-analytics/trends", {
    query,
  });
}

// ── Knowledge Gaps ─────────────────────────────────────────────────────────────

export type GapType =
  | "no_answer"
  | "low_confidence"
  | "bad_feedback"
  | "stale_citation"
  | "missing_source";

export type GapStatus = "open" | "in_review" | "resolved" | "dismissed";

export type GapSource =
  | "admin"
  | "low_confidence_analysis"
  | "feedback_analysis"
  | "no_answer_analysis";

export type KnowledgeGapResponse = {
  gap_id: string;
  organization_id: string;
  gap_type: GapType;
  topic_label: string;
  description: string | null;
  gap_source: GapSource;
  occurrence_count: number;
  avg_confidence: number | null;
  example_query: string | null;
  status: GapStatus;
  remediation_json: Record<string, unknown> | null;
  collection_id: string | null;
  linked_document_id: string | null;
  linked_eval_question_id: string | null;
  converted_to: "eval_case" | "doc_request" | "review_task" | null;
  converted_at: string | null;
  reviewer_notes: string | null;
  created_at: string;
  updated_at: string;
};

export type KnowledgeGapListResponse = {
  items: KnowledgeGapResponse[];
  total: number;
};

export type ListGapsOptions = {
  status?: GapStatus;
  gap_type?: GapType;
  limit?: number;
  offset?: number;
};

export async function listKnowledgeGaps(
  options: ListGapsOptions = {},
): Promise<KnowledgeGapListResponse> {
  return apiRequest<KnowledgeGapListResponse>("/admin/query-analytics/gaps", {
    query: {
      status: options.status,
      gap_type: options.gap_type,
      limit: options.limit,
      offset: options.offset,
    },
  });
}

export type CreateKnowledgeGapRequest = {
  gap_type: GapType;
  topic_label: string;
  description?: string | null;
  occurrence_count?: number;
  avg_confidence?: number | null;
  example_query?: string | null;
  collection_id?: string | null;
  gap_source?: GapSource;
};

export async function createKnowledgeGap(
  payload: CreateKnowledgeGapRequest,
): Promise<KnowledgeGapResponse> {
  return apiRequest<KnowledgeGapResponse>("/admin/query-analytics/gaps", {
    method: "POST",
    json: payload,
  });
}

export type UpdateKnowledgeGapRequest = {
  status?: GapStatus;
  reviewer_notes?: string | null;
  linked_document_id?: string | null;
  description?: string | null;
};

export async function updateKnowledgeGap(
  gapId: string,
  payload: UpdateKnowledgeGapRequest,
): Promise<KnowledgeGapResponse> {
  return apiRequest<KnowledgeGapResponse>(
    `/admin/query-analytics/gaps/${encodeURIComponent(gapId)}`,
    { method: "PATCH", json: payload },
  );
}

export type ConvertKnowledgeGapRequest = {
  target: "eval_case" | "doc_request" | "review_task";
  evaluation_set_id?: string | null;
  notes?: string | null;
};

export type ConvertKnowledgeGapResponse = {
  gap_id: string;
  converted_to: string;
  converted_at: string;
  linked_eval_question_id: string | null;
};

export async function convertKnowledgeGap(
  gapId: string,
  payload: ConvertKnowledgeGapRequest,
): Promise<ConvertKnowledgeGapResponse> {
  return apiRequest<ConvertKnowledgeGapResponse>(
    `/admin/query-analytics/gaps/${encodeURIComponent(gapId)}/convert`,
    { method: "POST", json: payload },
  );
}

export type DetectGapsRequest = {
  from_date?: string | null;
  to_date?: string | null;
  low_confidence_threshold?: number;
  min_occurrences?: number;
};

export type DetectGapsResponse = {
  detected: number;
  created: number;
  skipped_duplicates: number;
};

export async function detectKnowledgeGaps(
  payload: DetectGapsRequest = {},
): Promise<DetectGapsResponse> {
  return apiRequest<DetectGapsResponse>("/admin/query-analytics/gaps/detect", {
    method: "POST",
    json: payload,
  });
}

// ── Export ─────────────────────────────────────────────────────────────────────

export function buildQueryAnalyticsExportUrl(
  query: QueryAnalyticsSummaryQuery = {},
): string {
  const params = new URLSearchParams();
  if (query.from) params.set("from", query.from);
  if (query.to) params.set("to", query.to);
  const qs = params.toString();
  return `/api/admin/query-analytics/export${qs ? `?${qs}` : ""}`;
}
