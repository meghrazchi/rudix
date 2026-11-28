import type { Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest, apiRequestVoid } from "@/lib/api/request";

type Schemas = components["schemas"];

// ── Domain verification ───────────────────────────────────────────────────────

export type DomainVerificationStatus = "pending" | "verified" | "failed";

export type DomainVerification = Served<Schemas["DomainVerificationResponse"]>;

export type DomainCheckResult = Served<Schemas["DomainCheckResponse"]>;

export type InitiateDomainVerificationRequest =
  Schemas["InitiateDomainVerificationRequest"];

// ── SCIM config ───────────────────────────────────────────────────────────────

export type SCIMConfig = Served<Schemas["SCIMConfigResponse"]>;

export type SCIMEnableResponse = Served<Schemas["SCIMEnableResponse"]>;

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
