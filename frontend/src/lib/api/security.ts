import { apiRequest } from "@/lib/api/request";

function trimToNull(value: string | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed && trimmed.length > 0 ? trimmed : null;
}

// ── Capability flags ──────────────────────────────────────────────────────────

export type SecurityCapabilities = {
  sessionsEnabled: boolean;
  revokeSessionEnabled: boolean;
  revokeAllSessionsEnabled: boolean;
  loginPolicyEnabled: boolean;
  postureEnabled: boolean;
  auditEnabled: boolean;
  auditExportEnabled: boolean;
};

export class SecurityEndpointUnavailableError extends Error {
  readonly endpointKey: keyof SecurityCapabilities;

  constructor(endpointKey: keyof SecurityCapabilities) {
    super("Security endpoint is not configured");
    this.name = "SecurityEndpointUnavailableError";
    this.endpointKey = endpointKey;
  }
}

export function isSecurityEndpointUnavailableError(
  error: unknown,
): error is SecurityEndpointUnavailableError {
  return error instanceof SecurityEndpointUnavailableError;
}

function getSecurityEndpoints() {
  return {
    sessionsUrl: trimToNull(process.env.NEXT_PUBLIC_SECURITY_SESSIONS_URL),
    revokeSessionUrl: trimToNull(
      process.env.NEXT_PUBLIC_SECURITY_REVOKE_SESSION_URL,
    ),
    revokeAllSessionsUrl: trimToNull(
      process.env.NEXT_PUBLIC_SECURITY_REVOKE_ALL_SESSIONS_URL,
    ),
    loginPolicyUrl: trimToNull(
      process.env.NEXT_PUBLIC_SECURITY_LOGIN_POLICY_URL,
    ),
    postureUrl: trimToNull(process.env.NEXT_PUBLIC_SECURITY_POSTURE_URL),
    auditUrl: trimToNull(process.env.NEXT_PUBLIC_SECURITY_AUDIT_URL),
    auditExportUrl: trimToNull(
      process.env.NEXT_PUBLIC_SECURITY_AUDIT_EXPORT_URL,
    ),
  };
}

export function getSecurityCapabilities(): SecurityCapabilities {
  const e = getSecurityEndpoints();
  return {
    sessionsEnabled: e.sessionsUrl !== null,
    revokeSessionEnabled: e.revokeSessionUrl !== null,
    revokeAllSessionsEnabled: e.revokeAllSessionsUrl !== null,
    loginPolicyEnabled: e.loginPolicyUrl !== null,
    postureEnabled: e.postureUrl !== null,
    auditEnabled: e.auditUrl !== null,
    auditExportEnabled: e.auditExportUrl !== null,
  };
}

// ── Types ─────────────────────────────────────────────────────────────────────

export type SecuritySession = {
  id: string;
  device: string;
  ip_address: string | null;
  location: string | null;
  created_at: string | null;
  last_active_at: string | null;
  is_current: boolean;
};

export type LoginPolicy = {
  domain_allowlist: string[];
  session_timeout_hours: number | null;
  sso_required: boolean;
  invite_only: boolean;
  mfa_required: boolean;
};

export type SecurityPosture = {
  prompt_injection_protection: boolean | null;
  citation_validation: boolean | null;
  tenant_isolation: boolean | null;
  output_validation: boolean | null;
  tool_policy_enforced: boolean | null;
  last_audit_at: string | null;
};

export type AuditEvent = {
  id: string;
  event_type: string;
  actor_email: string | null;
  created_at: string;
  summary: string;
};

// ── API functions ─────────────────────────────────────────────────────────────

// ── Normalization ─────────────────────────────────────────────────────────────

type RawRecord = Record<string, unknown>;

function toRaw(payload: unknown): RawRecord {
  return typeof payload === "object" &&
    payload !== null &&
    !Array.isArray(payload)
    ? (payload as RawRecord)
    : {};
}

function asString(v: unknown, fallback = ""): string {
  return typeof v === "string" ? v : fallback;
}

function asStringOrNull(v: unknown): string | null {
  if (typeof v === "string" && v.trim().length > 0) return v.trim();
  return null;
}

function asBoolean(v: unknown, fallback: boolean): boolean {
  return typeof v === "boolean" ? v : fallback;
}

function asPositiveNumberOrNull(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v) && v > 0) return v;
  return null;
}

function asStringList(v: unknown): string[] {
  if (Array.isArray(v)) {
    return v.filter((x): x is string => typeof x === "string");
  }
  return [];
}

function normalizeSession(payload: unknown): SecuritySession {
  const r = toRaw(payload);
  return {
    id: asString(r.id),
    device: asString(r.device, "Unknown device"),
    ip_address: asStringOrNull(r.ip_address),
    location: asStringOrNull(r.location),
    created_at: asStringOrNull(r.created_at),
    last_active_at: asStringOrNull(r.last_active_at),
    is_current: asBoolean(r.is_current, false),
  };
}

function normalizeLoginPolicy(payload: unknown): LoginPolicy {
  const r = toRaw(payload);
  return {
    domain_allowlist: asStringList(r.domain_allowlist),
    session_timeout_hours: asPositiveNumberOrNull(r.session_timeout_hours),
    sso_required: asBoolean(r.sso_required, false),
    invite_only: asBoolean(r.invite_only, false),
    mfa_required: asBoolean(r.mfa_required, false),
  };
}

function normalizeSecurityPosture(payload: unknown): SecurityPosture {
  const r = toRaw(payload);
  return {
    prompt_injection_protection:
      typeof r.prompt_injection_protection === "boolean"
        ? r.prompt_injection_protection
        : null,
    citation_validation:
      typeof r.citation_validation === "boolean" ? r.citation_validation : null,
    tenant_isolation:
      typeof r.tenant_isolation === "boolean" ? r.tenant_isolation : null,
    output_validation:
      typeof r.output_validation === "boolean" ? r.output_validation : null,
    tool_policy_enforced:
      typeof r.tool_policy_enforced === "boolean"
        ? r.tool_policy_enforced
        : null,
    last_audit_at: asStringOrNull(r.last_audit_at),
  };
}

function normalizeAuditEvent(payload: unknown): AuditEvent {
  const r = toRaw(payload);
  return {
    id: asString(r.id),
    event_type: asString(r.event_type),
    actor_email: asStringOrNull(r.actor_email),
    created_at: asString(r.created_at),
    summary: asString(r.summary),
  };
}

// ── API functions ─────────────────────────────────────────────────────────────

export async function getSessions(): Promise<SecuritySession[]> {
  const { sessionsUrl } = getSecurityEndpoints();
  if (!sessionsUrl)
    throw new SecurityEndpointUnavailableError("sessionsEnabled");
  const payload = await apiRequest<unknown>(sessionsUrl, {
    method: "GET",
    retry: false,
  });
  if (Array.isArray(payload)) return payload.map(normalizeSession);
  const r = toRaw(payload);
  if (Array.isArray(r.items))
    return (r.items as unknown[]).map(normalizeSession);
  return [];
}

export async function revokeSession(sessionId: string): Promise<void> {
  const { revokeSessionUrl } = getSecurityEndpoints();
  if (!revokeSessionUrl)
    throw new SecurityEndpointUnavailableError("revokeSessionEnabled");
  await apiRequest(`${revokeSessionUrl}/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
    retry: false,
  });
}

export async function revokeAllOtherSessions(): Promise<void> {
  const { revokeAllSessionsUrl } = getSecurityEndpoints();
  if (!revokeAllSessionsUrl)
    throw new SecurityEndpointUnavailableError("revokeAllSessionsEnabled");
  await apiRequest(revokeAllSessionsUrl, { method: "POST", retry: false });
}

export async function getLoginPolicy(): Promise<LoginPolicy> {
  const { loginPolicyUrl } = getSecurityEndpoints();
  if (!loginPolicyUrl)
    throw new SecurityEndpointUnavailableError("loginPolicyEnabled");
  const payload = await apiRequest<unknown>(loginPolicyUrl, {
    method: "GET",
    retry: false,
  });
  return normalizeLoginPolicy(payload);
}

export async function updateLoginPolicy(
  policy: Partial<LoginPolicy>,
): Promise<LoginPolicy> {
  const { loginPolicyUrl } = getSecurityEndpoints();
  if (!loginPolicyUrl)
    throw new SecurityEndpointUnavailableError("loginPolicyEnabled");
  const payload = await apiRequest<unknown>(loginPolicyUrl, {
    method: "PATCH",
    json: policy,
    retry: false,
  });
  return normalizeLoginPolicy(payload);
}

export async function getSecurityPosture(): Promise<SecurityPosture> {
  const { postureUrl } = getSecurityEndpoints();
  if (!postureUrl) throw new SecurityEndpointUnavailableError("postureEnabled");
  const payload = await apiRequest<unknown>(postureUrl, {
    method: "GET",
    retry: false,
  });
  return normalizeSecurityPosture(payload);
}

export async function getRecentAuditEvents(): Promise<AuditEvent[]> {
  const limit = 5;
  const { auditUrl } = getSecurityEndpoints();
  if (!auditUrl) throw new SecurityEndpointUnavailableError("auditEnabled");
  const payload = await apiRequest<unknown>(auditUrl, {
    method: "GET",
    query: { limit },
    retry: false,
  });
  if (Array.isArray(payload)) return payload.map(normalizeAuditEvent);
  const r = toRaw(payload);
  if (Array.isArray(r.items))
    return (r.items as unknown[]).map(normalizeAuditEvent);
  return [];
}
