import type { Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

export type UsageGranularity = "day" | "week" | "month";

export type UsageSummaryPoint = Served<Schemas["UsageSummaryPointResponse"]>;

export type UsageSummaryResponse = Served<Schemas["UsageSummaryResponse"]>;

export type UsageSummaryQuery = {
  from?: string;
  to?: string;
  granularity?: UsageGranularity;
  user_id?: string;
};

export type AuditLogListItemResponse = Served<
  Schemas["AuditLogListItemResponse"]
>;

export type AuditLogListResponse = Served<Schemas["AuditLogListResponse"]>;

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

export type TopUserUsage = Served<Schemas["TopUserUsageResponse"]>;

export type TopModelUsage = Served<Schemas["TopModelUsageResponse"]>;

export type UsageDashboardTotals = Served<
  Schemas["UsageDashboardTotalsResponse"]
>;

export type UsageDashboardPoint = Served<
  Schemas["UsageDashboardPointResponse"]
>;

export type UsageDashboardResponse = Served<Schemas["UsageDashboardResponse"]>;

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
