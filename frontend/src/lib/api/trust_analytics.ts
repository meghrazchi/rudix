import { apiRequest } from "@/lib/api/request";

export type TrustAnalyticsDateRange = {
  from: string;
  to: string;
};

export type TrustDistribution = {
  high_count: number;
  medium_count: number;
  low_count: number;
  warning_count: number;
  not_found_count: number;
  high_pct: number | null;
  medium_pct: number | null;
  low_pct: number | null;
  warning_pct: number | null;
  not_found_pct: number | null;
};

export type WarningBreakdown = {
  stale_source_count: number;
  conflict_count: number;
  ocr_count: number;
  extraction_count: number;
  processing_count: number;
  evidence_quality_count: number;
  citation_validation_failed_count: number;
};

export type TrustTrendPoint = {
  date: string;
  answer_count: number;
  not_found_count: number;
  not_found_rate: number | null;
  avg_confidence_score: number | null;
  avg_citation_support_score: number | null;
  high_trust_count: number;
  low_trust_count: number;
};

export type LangfuseIntegrationStatus = {
  enabled: boolean;
  traces_linked_count: number;
};

export type TrustAnalyticsResponse = {
  organization_id: string;
  range: TrustAnalyticsDateRange;
  generated_at: string;
  total_answers: number;
  not_found_rate: number | null;
  avg_confidence_score: number | null;
  avg_citation_support_score: number | null;
  avg_verification_support_score: number | null;
  unsupported_claims_removed_total: number;
  conflict_detection_rate: number | null;
  trust_distribution: TrustDistribution;
  warnings: WarningBreakdown;
  daily_trends: TrustTrendPoint[];
  langfuse: LangfuseIntegrationStatus;
  telemetry_missing: boolean;
};

export type TrustAnalyticsQuery = {
  from?: string;
  to?: string;
};

export async function getTrustAnalytics(
  query: TrustAnalyticsQuery = {},
): Promise<TrustAnalyticsResponse> {
  const params = new URLSearchParams();
  if (query.from) params.set("from", query.from);
  if (query.to) params.set("to", query.to);
  const qs = params.toString();
  return apiRequest<TrustAnalyticsResponse>(
    `/admin/trust-analytics${qs ? `?${qs}` : ""}`,
  );
}
