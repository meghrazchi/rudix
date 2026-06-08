import { apiRequest } from "@/lib/api/request";

export type UsageGranularity = "day" | "week" | "month";

export type UsageSummaryPoint = {
  period_start: string;
  period_end: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  event_count: number;
  avg_confidence?: number | null;
  avg_latency_ms?: number | null;
  latency_score?: number | null;
};

export type UsageSummaryResponse = {
  organization_id: string;
  range: {
    from: string;
    to: string;
  };
  granularity?: UsageGranularity;
  totals: {
    input_tokens: number;
    output_tokens: number;
    cost_usd: number;
    event_count: number;
    avg_confidence?: number | null;
    avg_latency_ms?: number | null;
    latency_score?: number | null;
  };
  series: UsageSummaryPoint[];
};

export type UsageSummaryQuery = {
  from?: string;
  to?: string;
  granularity?: UsageGranularity;
  user_id?: string;
};

export type AuditLogListItemResponse = {
  audit_log_id: string;
  organization_id: string;
  user_id: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  request_id: string | null;
  result?: "success" | "failure" | "unknown";
  severity?: string | null;
  ip_address?: string | null;
  session_id?: string | null;
  document_id?: string | null;
  collection_id?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type AuditLogListResponse = {
  items: AuditLogListItemResponse[];
  total: number;
  limit: number;
  offset: number;
  range: {
    from: string;
    to: string;
  };
};

export type AuditLogListQuery = {
  from?: string;
  to?: string;
  organization_id?: string;
  actor?: string;
  limit?: number;
  offset?: number;
  user_id?: string;
  action?: string;
  entity?: string;
  resource_type?: string;
  resource_id?: string;
  document_id?: string;
  collection_id?: string;
  request_id?: string;
  session_id?: string;
  ip_address?: string;
  result?: "all" | "success" | "failure" | "unknown";
  severity?: string;
  search?: string;
};

export type AuditLogExportFormat = "csv" | "json";

export async function getUsageSummary(
  query: UsageSummaryQuery = {},
): Promise<UsageSummaryResponse> {
  return apiRequest<UsageSummaryResponse>("/admin/usage", {
    query,
  });
}

export async function listAuditLogs(
  query: AuditLogListQuery = {},
): Promise<AuditLogListResponse> {
  return apiRequest<AuditLogListResponse>("/admin/audit-logs", {
    query,
  });
}

export async function exportAuditLogs(
  format: AuditLogExportFormat,
  query: AuditLogListQuery = {},
): Promise<Blob> {
  return apiRequest<Blob>("/admin/audit-logs/export", {
    query: {
      ...query,
      format,
    },
    responseType: "blob",
  });
}

// ── Usage Dashboard (F153) ────────────────────────────────────────────────────

export type FeatureArea =
  | "chat"
  | "agent"
  | "evaluation"
  | "pipeline"
  | "api"
  | "all";
export type UsageExportFormat = "csv" | "json";

export type TopUserUsage = {
  user_id: string;
  questions: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
};

export type TopModelUsage = {
  model_name: string;
  event_count: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
};

export type UsageDashboardTotals = {
  questions_asked: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
  active_users: number;
  documents: number;
  indexed_documents: number;
  total_chunks: number;
  indexing_jobs: number;
  failed_indexing_jobs: number;
  evaluation_runs: number;
  agent_runs: number;
  api_calls: number;
  avg_confidence: number | null;
  avg_latency_ms: number | null;
  latency_score: number | null;
};

export type UsageDashboardPoint = {
  period_start: string;
  period_end: string;
  questions_asked: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
  active_users: number;
  agent_runs: number;
  evaluation_runs: number;
  avg_confidence: number | null;
  avg_latency_ms: number | null;
};

export type UsageDashboardResponse = {
  organization_id: string;
  range: { from: string; to: string };
  granularity: UsageGranularity;
  is_cost_estimate: boolean;
  totals: UsageDashboardTotals;
  series: UsageDashboardPoint[];
  top_users: TopUserUsage[];
  top_models: TopModelUsage[];
  feature_area_breakdown: Record<string, number>;
};

export type UsageDashboardQuery = {
  from?: string;
  to?: string;
  granularity?: UsageGranularity;
  user_id?: string;
  model?: string;
  feature_area?: FeatureArea;
};

export async function getUsageDashboard(
  query: UsageDashboardQuery = {},
): Promise<UsageDashboardResponse> {
  return apiRequest<UsageDashboardResponse>("/admin/usage/dashboard", {
    query,
  });
}

export async function exportUsageDashboard(
  format: UsageExportFormat,
  query: UsageDashboardQuery = {},
): Promise<Blob> {
  return apiRequest<Blob>("/admin/usage/export", {
    query: { ...query, format },
    responseType: "blob",
  });
}
