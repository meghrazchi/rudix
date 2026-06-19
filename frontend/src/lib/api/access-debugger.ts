import { apiRequest } from "@/lib/api/request";

const BASE = "/admin/access-debugger";

// ── Types ─────────────────────────────────────────────────────────────────────

export type OrgMemberResult = {
  user_id: string;
  display_name: string | null;
  email: string;
  role: string;
};

export type OrgMemberListResponse = {
  items: OrgMemberResult[];
  total: number;
};

export type SimulateAccessRequest = {
  subject_user_id: string;
  resource_type: string;
  action: string;
  resource_id?: string | null;
};

export type SimulateTraceStep = {
  rule: string;
  outcome: "pass" | "allow" | "deny";
  detail: string | null;
};

export type ReasonChainEntry = {
  layer: string;
  outcome: "pass" | "allow" | "deny";
  detail: string | null;
};

export type TroubleshootingLink = {
  label: string;
  href: string;
};

export type ExtendedStatus =
  | "allowed"
  | "denied"
  | "inherited"
  | "restricted"
  | "stale_acl"
  | "unavailable"
  | "unknown";

export type SimulateAccessResponse = {
  decision: "allow" | "deny";
  extended_status: ExtendedStatus;
  matched_rule: string;
  deny_reason: string | null;
  subject_user_id: string;
  subject_display_name: string | null;
  subject_email: string;
  subject_role: string;
  resource_type: string;
  resource_id: string | null;
  action: string;
  trace: SimulateTraceStep[];
  reason_chain: ReasonChainEntry[];
  effective_permissions: string[];
  remediation: string[];
  troubleshooting_links: TroubleshootingLink[];
  request_id: string;
};

// ── Normalizers ────────────────────────────────────────────────────────────────

function normalizeOrgMember(value: unknown): OrgMemberResult {
  const raw = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return {
    user_id: typeof raw.user_id === "string" ? raw.user_id : "",
    display_name: typeof raw.display_name === "string" ? raw.display_name : null,
    email: typeof raw.email === "string" ? raw.email : "",
    role: typeof raw.role === "string" ? raw.role : "",
  };
}

function normalizeTraceStep(value: unknown): SimulateTraceStep {
  const raw = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return {
    rule: typeof raw.rule === "string" ? raw.rule : "",
    outcome: (raw.outcome as SimulateTraceStep["outcome"]) ?? "pass",
    detail: typeof raw.detail === "string" ? raw.detail : null,
  };
}

function normalizeReasonChainEntry(value: unknown): ReasonChainEntry {
  const raw = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return {
    layer: typeof raw.layer === "string" ? raw.layer : "",
    outcome: (raw.outcome as ReasonChainEntry["outcome"]) ?? "pass",
    detail: typeof raw.detail === "string" ? raw.detail : null,
  };
}

function normalizeTroubleshootingLink(value: unknown): TroubleshootingLink {
  const raw = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return {
    label: typeof raw.label === "string" ? raw.label : "",
    href: typeof raw.href === "string" ? raw.href : "",
  };
}

function normalizeSimulateResponse(value: unknown): SimulateAccessResponse {
  const raw = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return {
    decision: raw.decision === "allow" ? "allow" : "deny",
    extended_status: (raw.extended_status as ExtendedStatus) ?? "unknown",
    matched_rule: typeof raw.matched_rule === "string" ? raw.matched_rule : "",
    deny_reason: typeof raw.deny_reason === "string" ? raw.deny_reason : null,
    subject_user_id: typeof raw.subject_user_id === "string" ? raw.subject_user_id : "",
    subject_display_name:
      typeof raw.subject_display_name === "string" ? raw.subject_display_name : null,
    subject_email: typeof raw.subject_email === "string" ? raw.subject_email : "",
    subject_role: typeof raw.subject_role === "string" ? raw.subject_role : "",
    resource_type: typeof raw.resource_type === "string" ? raw.resource_type : "",
    resource_id: typeof raw.resource_id === "string" ? raw.resource_id : null,
    action: typeof raw.action === "string" ? raw.action : "",
    trace: Array.isArray(raw.trace) ? raw.trace.map(normalizeTraceStep) : [],
    reason_chain: Array.isArray(raw.reason_chain)
      ? raw.reason_chain.map(normalizeReasonChainEntry)
      : [],
    effective_permissions: Array.isArray(raw.effective_permissions)
      ? (raw.effective_permissions as unknown[]).filter((p): p is string => typeof p === "string")
      : [],
    remediation: Array.isArray(raw.remediation)
      ? (raw.remediation as unknown[]).filter((r): r is string => typeof r === "string")
      : [],
    troubleshooting_links: Array.isArray(raw.troubleshooting_links)
      ? raw.troubleshooting_links.map(normalizeTroubleshootingLink)
      : [],
    request_id: typeof raw.request_id === "string" ? raw.request_id : "",
  };
}

// ── API functions ──────────────────────────────────────────────────────────────

export async function searchOrgUsers(params?: {
  q?: string;
  limit?: number;
}): Promise<OrgMemberListResponse> {
  const qs = new URLSearchParams();
  if (params?.q) qs.set("q", params.q);
  if (params?.limit) qs.set("limit", String(params.limit));
  const url = `${BASE}/users${qs.size ? `?${qs}` : ""}`;
  const payload = await apiRequest<unknown>(url, { method: "GET", retry: false });
  const raw = payload && typeof payload === "object" ? (payload as Record<string, unknown>) : {};
  return {
    items: Array.isArray(raw.items) ? raw.items.map(normalizeOrgMember) : [],
    total: typeof raw.total === "number" ? raw.total : 0,
  };
}

export async function simulateAccess(req: SimulateAccessRequest): Promise<SimulateAccessResponse> {
  const payload = await apiRequest<unknown>(`${BASE}/simulate`, {
    method: "POST",
    json: req,
    retry: false,
  });
  return normalizeSimulateResponse(payload);
}
