import { apiRequest } from "@/lib/api/request";

export type SloSuggestion = {
  metric: string;
  current_value: number;
  suggested_threshold: number;
  unit: string;
  rationale: string;
};

export type ProviderHealthCard = {
  provider_key: string;
  total_events: number;
  failed_events: number;
  failure_rate: number | null;
  timed_out_events: number;
  timeout_rate: number | null;
  fallback_events: number;
  fallback_rate: number | null;
  retry_events: number;
  retry_rate: number | null;
  avg_retry_count: number | null;
  avg_latency_ms: number | null;
  p95_latency_ms: number | null;
  slo_suggestions: SloSuggestion[];
  telemetry_missing: boolean;
};

export type ProviderObservabilityRange = {
  from: string;
  to: string;
};

export type ProviderObservabilitySnapshot = {
  organization_id: string;
  range: ProviderObservabilityRange;
  generated_at: string;
  providers: ProviderHealthCard[];
  telemetry_missing: boolean;
};

export type ProviderObservabilityQuery = {
  from?: string;
  to?: string;
};

export async function getProviderObservabilitySnapshot(
  query?: ProviderObservabilityQuery,
): Promise<ProviderObservabilitySnapshot> {
  const params = new URLSearchParams();
  if (query?.from) params.set("from", query.from);
  if (query?.to) params.set("to", query.to);
  const qs = params.toString();
  return apiRequest<ProviderObservabilitySnapshot>(
    `/admin/provider-observability${qs ? `?${qs}` : ""}`,
  );
}
