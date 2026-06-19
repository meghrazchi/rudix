import { apiRequest } from "@/lib/api/request";

const BASE = "/admin/permissions";

// ── Types ─────────────────────────────────────────────────────────────────────

export type ConflictSeverity = "info" | "warning" | "blocking" | "security_risk";
export type ConflictStatus = "open" | "investigating" | "resolved" | "dismissed";

export type ConflictEntry = {
  id: string;
  organization_id: string;
  subject_type: string;
  subject_value: string;
  user_id: string | null;
  role_name: string | null;
  resource_type: string;
  resource_id: string | null;
  action: string;
  conflict_type: string;
  severity: ConflictSeverity;
  status: ConflictStatus;
  detected_at: string;
  resolved_at: string | null;
  conflict_summary: string | null;
  grant_id: string | null;
  deny_id: string | null;
  remediation: string[];
  context: Record<string, unknown>;
};

export type ConflictListResponse = {
  items: ConflictEntry[];
  total: number;
  page: number;
  page_size: number;
};

export type UpdateConflictStatusRequest = {
  status: "investigating" | "resolved" | "dismissed";
  resolution_note?: string | null;
};

export type ScanResult = {
  conflicts_detected: number;
  conflicts_created: number;
  scan_duration_ms: number;
  scanned_grants: number;
  scanned_denies: number;
  scanned_acl_mappings: number;
};

export type TraceStep = {
  rule: string;
  outcome: "pass" | "allow" | "deny";
  detail: string | null;
};

export type ExplainDecisionResponse = {
  decision: "allow" | "deny";
  matched_rule: string;
  deny_reason: string | null;
  subject_user_id: string;
  resource_type: string;
  resource_id: string | null;
  action: string;
  trace: TraceStep[];
  remediation: string[];
  request_id: string;
};

// ── Normalizers ────────────────────────────────────────────────────────────────

function normalizeConflictEntry(value: unknown): ConflictEntry {
  const raw = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return {
    id: typeof raw.id === "string" ? raw.id : "",
    organization_id: typeof raw.organization_id === "string" ? raw.organization_id : "",
    subject_type: typeof raw.subject_type === "string" ? raw.subject_type : "",
    subject_value: typeof raw.subject_value === "string" ? raw.subject_value : "",
    user_id: typeof raw.user_id === "string" ? raw.user_id : null,
    role_name: typeof raw.role_name === "string" ? raw.role_name : null,
    resource_type: typeof raw.resource_type === "string" ? raw.resource_type : "",
    resource_id: typeof raw.resource_id === "string" ? raw.resource_id : null,
    action: typeof raw.action === "string" ? raw.action : "",
    conflict_type: typeof raw.conflict_type === "string" ? raw.conflict_type : "",
    severity: (raw.severity as ConflictSeverity) ?? "info",
    status: (raw.status as ConflictStatus) ?? "open",
    detected_at: typeof raw.detected_at === "string" ? raw.detected_at : "",
    resolved_at: typeof raw.resolved_at === "string" ? raw.resolved_at : null,
    conflict_summary: typeof raw.conflict_summary === "string" ? raw.conflict_summary : null,
    grant_id: typeof raw.grant_id === "string" ? raw.grant_id : null,
    deny_id: typeof raw.deny_id === "string" ? raw.deny_id : null,
    remediation: Array.isArray(raw.remediation)
      ? (raw.remediation as unknown[]).filter((r): r is string => typeof r === "string")
      : [],
    context:
      raw.context && typeof raw.context === "object"
        ? (raw.context as Record<string, unknown>)
        : {},
  };
}

function normalizeTraceStep(value: unknown): TraceStep {
  const raw = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return {
    rule: typeof raw.rule === "string" ? raw.rule : "",
    outcome: (raw.outcome as TraceStep["outcome"]) ?? "pass",
    detail: typeof raw.detail === "string" ? raw.detail : null,
  };
}

// ── API functions ──────────────────────────────────────────────────────────────

export async function listConflicts(params?: {
  severity?: ConflictSeverity;
  status?: ConflictStatus;
  resource_type?: string;
  page?: number;
  page_size?: number;
}): Promise<ConflictListResponse> {
  const qs = new URLSearchParams();
  if (params?.severity) qs.set("severity", params.severity);
  if (params?.status) qs.set("status", params.status);
  if (params?.resource_type) qs.set("resource_type", params.resource_type);
  if (params?.page) qs.set("page", String(params.page));
  if (params?.page_size) qs.set("page_size", String(params.page_size));
  const url = `${BASE}/conflicts${qs.size ? `?${qs}` : ""}`;
  const payload = await apiRequest<unknown>(url, { method: "GET", retry: false });
  const raw = payload && typeof payload === "object" ? (payload as Record<string, unknown>) : {};
  return {
    items: Array.isArray(raw.items) ? raw.items.map(normalizeConflictEntry) : [],
    total: typeof raw.total === "number" ? raw.total : 0,
    page: typeof raw.page === "number" ? raw.page : 1,
    page_size: typeof raw.page_size === "number" ? raw.page_size : 50,
  };
}

export async function getConflict(conflictId: string): Promise<ConflictEntry> {
  const payload = await apiRequest<unknown>(
    `${BASE}/conflicts/${encodeURIComponent(conflictId)}`,
    { method: "GET", retry: false },
  );
  return normalizeConflictEntry(payload);
}

export async function updateConflictStatus(
  conflictId: string,
  req: UpdateConflictStatusRequest,
): Promise<ConflictEntry> {
  const payload = await apiRequest<unknown>(
    `${BASE}/conflicts/${encodeURIComponent(conflictId)}/status`,
    { method: "PATCH", json: req, retry: false },
  );
  return normalizeConflictEntry(payload);
}

export async function scanForConflicts(): Promise<ScanResult> {
  const payload = await apiRequest<unknown>(`${BASE}/conflicts/scan`, {
    method: "POST",
    retry: false,
  });
  const raw = payload && typeof payload === "object" ? (payload as Record<string, unknown>) : {};
  return {
    conflicts_detected: typeof raw.conflicts_detected === "number" ? raw.conflicts_detected : 0,
    conflicts_created: typeof raw.conflicts_created === "number" ? raw.conflicts_created : 0,
    scan_duration_ms: typeof raw.scan_duration_ms === "number" ? raw.scan_duration_ms : 0,
    scanned_grants: typeof raw.scanned_grants === "number" ? raw.scanned_grants : 0,
    scanned_denies: typeof raw.scanned_denies === "number" ? raw.scanned_denies : 0,
    scanned_acl_mappings: typeof raw.scanned_acl_mappings === "number" ? raw.scanned_acl_mappings : 0,
  };
}

export async function explainDecision(params: {
  subject_user_id: string;
  resource_type: string;
  action: string;
  resource_id?: string | null;
}): Promise<ExplainDecisionResponse> {
  const qs = new URLSearchParams({
    subject_user_id: params.subject_user_id,
    resource_type: params.resource_type,
    action: params.action,
  });
  if (params.resource_id) qs.set("resource_id", params.resource_id);
  const payload = await apiRequest<unknown>(
    `${BASE}/explain-decision?${qs}`,
    { method: "GET", retry: false },
  );
  const raw = payload && typeof payload === "object" ? (payload as Record<string, unknown>) : {};
  return {
    decision: raw.decision === "allow" ? "allow" : "deny",
    matched_rule: typeof raw.matched_rule === "string" ? raw.matched_rule : "",
    deny_reason: typeof raw.deny_reason === "string" ? raw.deny_reason : null,
    subject_user_id: typeof raw.subject_user_id === "string" ? raw.subject_user_id : "",
    resource_type: typeof raw.resource_type === "string" ? raw.resource_type : "",
    resource_id: typeof raw.resource_id === "string" ? raw.resource_id : null,
    action: typeof raw.action === "string" ? raw.action : "",
    trace: Array.isArray(raw.trace) ? raw.trace.map(normalizeTraceStep) : [],
    remediation: Array.isArray(raw.remediation)
      ? (raw.remediation as unknown[]).filter((r): r is string => typeof r === "string")
      : [],
    request_id: typeof raw.request_id === "string" ? raw.request_id : "",
  };
}
