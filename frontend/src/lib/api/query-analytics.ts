import type { Overlay, Served, WithOptional } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

// ── Shared types ───────────────────────────────────────────────────────────────

export type QueryAnalyticsDateRange = Served<
  Schemas["QueryAnalyticsDateRange"]
>;

// ── Summary ────────────────────────────────────────────────────────────────────

export type FeedbackCategoryCount = Served<Schemas["FeedbackCategoryCount"]>;

export type QueryAnalyticsSummaryResponse = Served<
  Schemas["QueryAnalyticsSummaryResponse"]
>;

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

export type QueryTrendPoint = Served<Schemas["QueryTrendPoint"]>;

export type QueryTrendsResponse = Served<Schemas["QueryTrendsResponse"]>;

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

export type KnowledgeGapResponse = Overlay<
  Served<Schemas["KnowledgeGapResponse"]>,
  {
    gap_type: GapType;
    gap_source: GapSource;
    status: GapStatus;
    converted_to: "eval_case" | "doc_request" | "review_task" | null;
  }
>;

export type KnowledgeGapListResponse = Overlay<
  Served<Schemas["KnowledgeGapListResponse"]>,
  { items: KnowledgeGapResponse[] }
>;

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

export type CreateKnowledgeGapRequest = Schemas["CreateKnowledgeGapRequest"];

export async function createKnowledgeGap(
  payload: CreateKnowledgeGapRequest,
): Promise<KnowledgeGapResponse> {
  return apiRequest<KnowledgeGapResponse>("/admin/query-analytics/gaps", {
    method: "POST",
    json: payload,
  });
}

export type UpdateKnowledgeGapRequest = Schemas["UpdateKnowledgeGapRequest"];

export async function updateKnowledgeGap(
  gapId: string,
  payload: UpdateKnowledgeGapRequest,
): Promise<KnowledgeGapResponse> {
  return apiRequest<KnowledgeGapResponse>(
    `/admin/query-analytics/gaps/${encodeURIComponent(gapId)}`,
    { method: "PATCH", json: payload },
  );
}

export type ConvertKnowledgeGapRequest = Schemas["ConvertKnowledgeGapRequest"];

export type ConvertKnowledgeGapResponse = Served<
  Schemas["ConvertKnowledgeGapResponse"]
>;

export async function convertKnowledgeGap(
  gapId: string,
  payload: ConvertKnowledgeGapRequest,
): Promise<ConvertKnowledgeGapResponse> {
  return apiRequest<ConvertKnowledgeGapResponse>(
    `/admin/query-analytics/gaps/${encodeURIComponent(gapId)}/convert`,
    { method: "POST", json: payload },
  );
}

export type DetectGapsRequest = WithOptional<
  Schemas["DetectGapsRequest"],
  "low_confidence_threshold" | "min_occurrences"
>;

export type DetectGapsResponse = Served<Schemas["DetectGapsResponse"]>;

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
