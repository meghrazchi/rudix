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
  limit?: number;
  offset?: number;
  user_id?: string;
  action?: string;
  resource_type?: string;
};

export async function getUsageSummary(query: UsageSummaryQuery = {}): Promise<UsageSummaryResponse> {
  return apiRequest<UsageSummaryResponse>("/admin/usage", {
    query,
  });
}

export async function listAuditLogs(query: AuditLogListQuery = {}): Promise<AuditLogListResponse> {
  return apiRequest<AuditLogListResponse>("/admin/audit-logs", {
    query,
  });
}
