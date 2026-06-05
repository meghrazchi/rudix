import { apiRequest, apiRequestVoid } from "@/lib/api/request";

// ── Domain verification ───────────────────────────────────────────────────────

export type DomainVerificationStatus = "pending" | "verified" | "failed";

export type DomainVerification = {
  id: string;
  organization_id: string;
  domain: string;
  status: DomainVerificationStatus;
  verification_token: string;
  txt_record_name: string;
  txt_record_value: string;
  verified_at: string | null;
  last_checked_at: string | null;
  failure_reason: string | null;
  created_at: string;
  updated_at: string;
};

export type DomainCheckResult = {
  id: string;
  domain: string;
  status: DomainVerificationStatus;
  verified_at: string | null;
  last_checked_at: string | null;
  failure_reason: string | null;
};

export type InitiateDomainVerificationRequest = {
  domain: string;
};

// ── SCIM config ───────────────────────────────────────────────────────────────

export type SCIMConfig = {
  id: string;
  organization_id: string;
  enabled: boolean;
  token_hint: string;
  scim_base_url: string;
  last_sync_at: string | null;
  last_sync_error: string | null;
  provisioned_count: number;
  deprovisioned_count: number;
  created_at: string;
  updated_at: string;
};

export type SCIMEnableResponse = {
  config: SCIMConfig;
  bearer_token: string;
};

// ── API functions ─────────────────────────────────────────────────────────────

export async function getSCIMConfig(): Promise<SCIMConfig | null> {
  return apiRequest<SCIMConfig | null>("/admin/scim");
}

export async function enableSCIM(): Promise<SCIMEnableResponse> {
  return apiRequest<SCIMEnableResponse>("/admin/scim/enable", {
    method: "POST",
  });
}

export async function rotateSCIMToken(): Promise<SCIMEnableResponse> {
  return apiRequest<SCIMEnableResponse>("/admin/scim/rotate-token", {
    method: "POST",
  });
}

export async function disableSCIM(): Promise<void> {
  return apiRequestVoid("/admin/scim", { method: "DELETE" });
}

export async function listDomainVerifications(): Promise<DomainVerification[]> {
  return apiRequest<DomainVerification[]>("/admin/scim/domains");
}

export async function initiateDomainVerification(
  payload: InitiateDomainVerificationRequest,
): Promise<DomainVerification> {
  return apiRequest<DomainVerification>("/admin/scim/domains", {
    method: "POST",
    json: payload,
  });
}

export async function checkDomainVerification(
  verificationId: string,
): Promise<DomainCheckResult> {
  return apiRequest<DomainCheckResult>(
    `/admin/scim/domains/${verificationId}/check`,
    { method: "POST" },
  );
}

export async function deleteDomainVerification(
  verificationId: string,
): Promise<void> {
  return apiRequestVoid(`/admin/scim/domains/${verificationId}`, {
    method: "DELETE",
  });
}
