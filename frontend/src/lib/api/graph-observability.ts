import { apiRequest } from "@/lib/api/request";

export type GraphObservabilityRange = {
  from: string;
  to: string;
};

export type GraphAlertLevel = "warning" | "critical";

export type GraphAlertItem = {
  level: GraphAlertLevel;
  metric: string;
  message: string;
};

export type GraphExtractionMetrics = {
  total_runs: number;
  succeeded: number;
  failed: number;
  running: number;
  skipped: number;
  success_rate: number | null;
  telemetry_missing: boolean;
};

export type GraphEntityTypeCount = {
  entity_type: string;
  count: number;
  avg_confidence: number | null;
};

export type GraphEntityMetrics = {
  total_entities: number;
  by_type: GraphEntityTypeCount[];
  avg_confidence: number | null;
  low_confidence_count: number;
  telemetry_missing: boolean;
};

export type GraphRelationMetrics = {
  total_relations: number;
  avg_confidence: number | null;
  low_confidence_count: number;
  telemetry_missing: boolean;
};

export type GraphQueryMetrics = {
  graphrag_queries: number;
  graphrag_failures: number;
  failure_rate: number | null;
  avg_expansion_size: number | null;
  avg_latency_ms: number | null;
  p95_latency_ms: number | null;
  fallback_to_rag: number;
  fallback_rate: number | null;
  cypher_failures: number;
  cypher_failure_rate: number | null;
  telemetry_missing: boolean;
};

export type GraphAlertThresholds = {
  extraction_failure_rate_max: number;
  query_failure_rate_max: number;
  graphrag_fallback_rate_max: number;
  low_confidence_entity_rate_max: number;
  query_latency_ms_max: number;
};

export type GraphTrendPoint = {
  day: string;
  extraction_runs: number;
  extraction_failure_rate: number | null;
  graphrag_queries: number;
  graphrag_failure_rate: number | null;
  fallback_rate: number | null;
  avg_latency_ms: number | null;
  cypher_failures: number;
};

export type GraphObservabilitySnapshot = {
  organization_id: string;
  range: GraphObservabilityRange;
  generated_at: string;
  graph_enabled: boolean;
  neo4j_reachable: boolean;
  extraction: GraphExtractionMetrics;
  entities: GraphEntityMetrics;
  relations: GraphRelationMetrics;
  queries: GraphQueryMetrics;
  thresholds: GraphAlertThresholds;
  alerts: GraphAlertItem[];
  trends: GraphTrendPoint[];
};

export type GraphObservabilityQuery = {
  from?: string;
  to?: string;
};

export async function getGraphObservabilitySnapshot(
  query?: GraphObservabilityQuery,
): Promise<GraphObservabilitySnapshot> {
  const params = new URLSearchParams();
  if (query?.from) params.set("from", query.from);
  if (query?.to) params.set("to", query.to);
  const qs = params.toString();
  return apiRequest<GraphObservabilitySnapshot>(
    `/admin/graph/observability${qs ? `?${qs}` : ""}`,
  );
}
