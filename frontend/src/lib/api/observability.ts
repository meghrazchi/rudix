import { apiRequest } from "@/lib/api/request";

export type ObservabilityRange = {
  from: string;
  to: string;
};

export type ApiMetrics = {
  total_requests: number;
  failed_requests: number;
  error_rate: number | null;
  avg_latency_ms: number | null;
  p95_latency_ms: number | null;
  telemetry_missing: boolean;
};

export type LlmModelSummary = {
  model_name: string;
  event_count: number;
  error_count: number;
};

export type LlmMetrics = {
  total_events: number;
  failed_events: number;
  error_rate: number | null;
  avg_latency_ms: number | null;
  top_models: LlmModelSummary[];
  telemetry_missing: boolean;
};

export type IndexingMetrics = {
  total_jobs: number;
  succeeded_jobs: number;
  failed_jobs: number;
  in_progress_jobs: number;
  success_rate: number | null;
  telemetry_missing: boolean;
};

export type StorageMetrics = {
  total_documents: number;
  indexed_documents: number;
  failed_documents: number;
  pending_documents: number;
  total_chunks: number;
};

export type ObservabilitySnapshot = {
  organization_id: string;
  range: ObservabilityRange;
  generated_at: string;
  api_metrics: ApiMetrics;
  llm_metrics: LlmMetrics;
  indexing_metrics: IndexingMetrics;
  storage_metrics: StorageMetrics;
};

export type ObservabilityQuery = {
  from?: string;
  to?: string;
};

export async function getObservabilitySnapshot(
  query?: ObservabilityQuery,
): Promise<ObservabilitySnapshot> {
  const params = new URLSearchParams();
  if (query?.from) params.set("from", query.from);
  if (query?.to) params.set("to", query.to);
  const qs = params.toString();
  return apiRequest<ObservabilitySnapshot>(
    `/admin/observability${qs ? `?${qs}` : ""}`,
  );
}
