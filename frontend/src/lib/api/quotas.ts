import type { Overlay, Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

// ---------------------------------------------------------------------------
// Enums / constants
// ---------------------------------------------------------------------------

export const QUOTA_TYPES = [
  "seats",
  "uploads",
  "questions",
  "tokens",
  "storage_bytes",
  "evaluations",
  "api_calls",
  "connectors",
  "agent_runs",
] as const;

export type QuotaType = (typeof QUOTA_TYPES)[number];

export const RESET_WINDOWS = [
  "per_minute",
  "per_hour",
  "per_day",
  "per_month",
  "none",
] as const;

export type ResetWindow = Served<Schemas["ResetWindow"]>;

// ---------------------------------------------------------------------------
// Shared types
// ---------------------------------------------------------------------------

export type QuotaLimitConfig = Served<Schemas["QuotaLimitConfig"]>;

export type QuotaUsageItem = Served<Schemas["QuotaUsageItem"]>;

// ---------------------------------------------------------------------------
// Policy
// ---------------------------------------------------------------------------

export type OrgQuotaPolicyResponse = Overlay<
  Served<Schemas["OrgQuotaPolicyResponse"]>,
  { limits: Partial<Record<QuotaType, QuotaLimitConfig>> }
>;

export type UpdateOrgQuotaPolicyRequest =
  Schemas["UpdateOrgQuotaPolicyRequest"];

export async function getQuotaPolicy(): Promise<OrgQuotaPolicyResponse> {
  return apiRequest<OrgQuotaPolicyResponse>("/admin/quotas/policy");
}

export async function updateQuotaPolicy(
  payload: UpdateOrgQuotaPolicyRequest,
): Promise<OrgQuotaPolicyResponse> {
  return apiRequest<OrgQuotaPolicyResponse>("/admin/quotas/policy", {
    method: "PATCH",
    json: payload,
  });
}

export async function resetQuotaPolicy(changeNote?: string): Promise<void> {
  return apiRequest<void>("/admin/quotas/policy", {
    method: "DELETE",
    query: changeNote ? { change_note: changeNote } : undefined,
  });
}

// ---------------------------------------------------------------------------
// Usage dashboard
// ---------------------------------------------------------------------------

export type OrgQuotaDashboardResponse = Served<
  Schemas["OrgQuotaDashboardResponse"]
>;

export async function getAdminQuotaUsage(): Promise<OrgQuotaDashboardResponse> {
  return apiRequest<OrgQuotaDashboardResponse>("/admin/quotas/usage");
}

export async function getMyQuotaUsage(): Promise<OrgQuotaDashboardResponse> {
  return apiRequest<OrgQuotaDashboardResponse>("/quotas/my-usage");
}

// ---------------------------------------------------------------------------
// Overrides
// ---------------------------------------------------------------------------

export type QuotaOverride = Served<Schemas["QuotaOverrideResponse"]>;

export type QuotaOverrideListResponse = Served<
  Schemas["QuotaOverrideListResponse"]
>;

export type CreateQuotaOverrideRequest = Schemas["CreateQuotaOverrideRequest"];

export async function listQuotaOverrides(
  params: {
    limit?: number;
    offset?: number;
  } = {},
): Promise<QuotaOverrideListResponse> {
  return apiRequest<QuotaOverrideListResponse>("/admin/quotas/overrides", {
    query: { limit: params.limit, offset: params.offset },
  });
}

export async function createQuotaOverride(
  payload: CreateQuotaOverrideRequest,
): Promise<QuotaOverride> {
  return apiRequest<QuotaOverride>("/admin/quotas/overrides", {
    method: "POST",
    json: payload,
  });
}

export async function deleteQuotaOverride(overrideId: string): Promise<void> {
  return apiRequest<void>(`/admin/quotas/overrides/${overrideId}`, {
    method: "DELETE",
  });
}

// ---------------------------------------------------------------------------
// Change log
// ---------------------------------------------------------------------------

export type QuotaChangeLogEntry = Served<
  Schemas["QuotaChangeLogEntryResponse"]
>;

export type QuotaChangeLogResponse = Served<Schemas["QuotaChangeLogResponse"]>;

export async function listQuotaChangeLog(
  params: {
    limit?: number;
    offset?: number;
  } = {},
): Promise<QuotaChangeLogResponse> {
  return apiRequest<QuotaChangeLogResponse>("/admin/quotas/change-log", {
    query: { limit: params.limit, offset: params.offset },
  });
}
