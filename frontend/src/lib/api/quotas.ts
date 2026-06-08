import { apiRequest } from "@/lib/api/request";

// ---------------------------------------------------------------------------
// Enums / constants
// ---------------------------------------------------------------------------

export const QUOTA_TYPES = [
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

export type ResetWindow = (typeof RESET_WINDOWS)[number];

// ---------------------------------------------------------------------------
// Shared types
// ---------------------------------------------------------------------------

export type QuotaLimitConfig = {
  soft_limit: number | null;
  hard_limit: number | null;
  reset_window: ResetWindow;
};

export type QuotaUsageItem = {
  quota_type: QuotaType;
  current_value: number;
  soft_limit: number | null;
  hard_limit: number | null;
  reset_window: ResetWindow;
  next_reset_at: string | null;
  near_limit: boolean;
  over_soft_limit: boolean;
  over_hard_limit: boolean;
};

// ---------------------------------------------------------------------------
// Policy
// ---------------------------------------------------------------------------

export type OrgQuotaPolicyResponse = {
  organization_id: string;
  limits: Partial<Record<QuotaType, QuotaLimitConfig>>;
  version: number;
  updated_by_id: string | null;
  updated_at: string;
};

export type UpdateOrgQuotaPolicyRequest = {
  uploads?: QuotaLimitConfig | null;
  questions?: QuotaLimitConfig | null;
  tokens?: QuotaLimitConfig | null;
  storage_bytes?: QuotaLimitConfig | null;
  evaluations?: QuotaLimitConfig | null;
  api_calls?: QuotaLimitConfig | null;
  connectors?: QuotaLimitConfig | null;
  agent_runs?: QuotaLimitConfig | null;
  change_note?: string | null;
};

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

export type OrgQuotaDashboardResponse = {
  organization_id: string;
  policy_version: number;
  quota_usage: QuotaUsageItem[];
  has_overages: boolean;
  checked_at: string;
};

export async function getAdminQuotaUsage(): Promise<OrgQuotaDashboardResponse> {
  return apiRequest<OrgQuotaDashboardResponse>("/admin/quotas/usage");
}

export async function getMyQuotaUsage(): Promise<OrgQuotaDashboardResponse> {
  return apiRequest<OrgQuotaDashboardResponse>("/quotas/my-usage");
}

// ---------------------------------------------------------------------------
// Overrides
// ---------------------------------------------------------------------------

export type QuotaOverride = {
  override_id: string;
  organization_id: string;
  quota_type: QuotaType;
  target_user_id: string | null;
  hard_limit_override: number | null;
  reason: string;
  created_by_id: string | null;
  expires_at: string | null;
  created_at: string;
};

export type QuotaOverrideListResponse = {
  items: QuotaOverride[];
  total: number;
};

export type CreateQuotaOverrideRequest = {
  quota_type: QuotaType;
  target_user_id?: string | null;
  hard_limit_override?: number | null;
  reason: string;
  expires_at?: string | null;
};

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

export type QuotaChangeLogEntry = {
  entry_id: string;
  organization_id: string;
  version_number: number;
  policy_snapshot: Record<string, unknown>;
  change_note: string | null;
  changed_by_id: string | null;
  created_at: string;
};

export type QuotaChangeLogResponse = {
  items: QuotaChangeLogEntry[];
  total: number;
};

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
