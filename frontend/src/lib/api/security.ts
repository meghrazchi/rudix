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

export async function getSessions(): Promise<SecuritySession[]> {
  const url = trimToNull(process.env.NEXT_PUBLIC_SECURITY_SESSIONS_URL);
  if (!url) throw new Error("Sessions endpoint is not configured.");
  return apiRequest<SecuritySession[]>(url);
}

export async function revokeSession(sessionId: string): Promise<void> {
  const baseUrl = trimToNull(
    process.env.NEXT_PUBLIC_SECURITY_REVOKE_SESSION_URL,
  );
  if (!baseUrl) throw new Error("Revoke session endpoint is not configured.");
  await apiRequest(`${baseUrl}/${sessionId}`, {
    method: "DELETE",
    retry: false,
  });
}

export async function revokeAllOtherSessions(): Promise<void> {
  const url = trimToNull(
    process.env.NEXT_PUBLIC_SECURITY_REVOKE_ALL_SESSIONS_URL,
  );
  if (!url)
    throw new Error("Revoke all sessions endpoint is not configured.");
  await apiRequest(url, { method: "POST", retry: false });
}

export async function getLoginPolicy(): Promise<LoginPolicy> {
  const url = trimToNull(process.env.NEXT_PUBLIC_SECURITY_LOGIN_POLICY_URL);
  if (!url) throw new Error("Login policy endpoint is not configured.");
  return apiRequest<LoginPolicy>(url);
}

export async function updateLoginPolicy(
  policy: Partial<LoginPolicy>,
): Promise<LoginPolicy> {
  const url = trimToNull(process.env.NEXT_PUBLIC_SECURITY_LOGIN_POLICY_URL);
  if (!url) throw new Error("Login policy endpoint is not configured.");
  return apiRequest<LoginPolicy>(url, {
    method: "PATCH",
    json: policy,
    retry: false,
  });
}

export async function getSecurityPosture(): Promise<SecurityPosture> {
  const url = trimToNull(process.env.NEXT_PUBLIC_SECURITY_POSTURE_URL);
  if (!url) throw new Error("Security posture endpoint is not configured.");
  return apiRequest<SecurityPosture>(url);
}

export async function getRecentAuditEvents(): Promise<AuditEvent[]> {
  const url = trimToNull(process.env.NEXT_PUBLIC_SECURITY_AUDIT_URL);
  if (!url) throw new Error("Audit endpoint is not configured.");
  return apiRequest<AuditEvent[]>(url, { query: { limit: 5 } });
}
