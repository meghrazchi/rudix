import type { Served, WithOptional } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type CitationMode = "required" | "recommended" | "disabled";
export type NoAnswerBehavior = "refuse" | "warn" | "allow";
export type StaleSourceBehavior = "warn" | "refuse" | "ignore";
export type DisclaimerPosition = "prepend" | "append";
export type PolicyOutcome = "allowed" | "blocked" | "warned";
export type PolicySource = "org" | "collection" | "none";

export type AiResponsePolicyResponse = Served<
  Schemas["AiResponsePolicyResponse"]
>;

export type AiResponsePolicyListResponse = Served<
  Schemas["AiResponsePolicyListResponse"]
>;

export type CreateAiResponsePolicyRequest = WithOptional<
  Schemas["CreateAiResponsePolicyRequest"],
  "grounded_verification_mode"
>;

export type UpdateAiResponsePolicyRequest =
  Schemas["UpdateAiResponsePolicyRequest"];

export type CollectionPolicyOverrideResponse = Served<
  Schemas["CollectionPolicyOverrideResponse"]
>;

export type UpsertCollectionPolicyOverrideRequest =
  Schemas["UpsertCollectionPolicyOverrideRequest"];

export type PolicyPreviewRequest = Schemas["PolicyPreviewRequest"];

export type PolicyPreviewResponse = Served<Schemas["PolicyPreviewResponse"]>;

export type PolicyEvaluationLogResponse = Served<
  Schemas["PolicyEvaluationLogResponse"]
>;

export type PolicyEvaluationLogListResponse = Served<
  Schemas["PolicyEvaluationLogListResponse"]
>;

// ---------------------------------------------------------------------------
// API functions — org policy CRUD
// ---------------------------------------------------------------------------

export async function listAiResponsePolicies(params?: {
  limit?: number;
  offset?: number;
}): Promise<AiResponsePolicyListResponse> {
  const qs = new URLSearchParams();
  if (params?.limit !== undefined) qs.set("limit", String(params.limit));
  if (params?.offset !== undefined) qs.set("offset", String(params.offset));
  const suffix = qs.toString() ? `?${qs}` : "";
  return apiRequest<AiResponsePolicyListResponse>(
    `/admin/ai-response-policy${suffix}`,
  );
}

export async function getActiveAiResponsePolicy(): Promise<AiResponsePolicyResponse | null> {
  return apiRequest<AiResponsePolicyResponse | null>(
    "/admin/ai-response-policy/active",
  );
}

export async function getAiResponsePolicy(
  policyId: string,
): Promise<AiResponsePolicyResponse> {
  return apiRequest<AiResponsePolicyResponse>(
    `/admin/ai-response-policy/${encodeURIComponent(policyId)}`,
  );
}

export async function createAiResponsePolicy(
  payload: CreateAiResponsePolicyRequest,
): Promise<AiResponsePolicyResponse> {
  return apiRequest<AiResponsePolicyResponse>("/admin/ai-response-policy", {
    method: "POST",
    json: payload,
  });
}

export async function updateAiResponsePolicy(
  policyId: string,
  payload: UpdateAiResponsePolicyRequest,
): Promise<AiResponsePolicyResponse> {
  return apiRequest<AiResponsePolicyResponse>(
    `/admin/ai-response-policy/${encodeURIComponent(policyId)}`,
    { method: "PATCH", json: payload },
  );
}

export async function deleteAiResponsePolicy(policyId: string): Promise<void> {
  await apiRequest<void>(
    `/admin/ai-response-policy/${encodeURIComponent(policyId)}`,
    { method: "DELETE" },
  );
}

export async function activateAiResponsePolicy(
  policyId: string,
): Promise<AiResponsePolicyResponse> {
  return apiRequest<AiResponsePolicyResponse>(
    `/admin/ai-response-policy/${encodeURIComponent(policyId)}/activate`,
    { method: "POST" },
  );
}

export async function deactivateAiResponsePolicy(
  policyId: string,
): Promise<AiResponsePolicyResponse> {
  return apiRequest<AiResponsePolicyResponse>(
    `/admin/ai-response-policy/${encodeURIComponent(policyId)}/deactivate`,
    { method: "POST" },
  );
}

// ---------------------------------------------------------------------------
// API functions — collection overrides
// ---------------------------------------------------------------------------

export async function upsertCollectionPolicyOverride(
  policyId: string,
  collectionId: string,
  payload: UpsertCollectionPolicyOverrideRequest,
): Promise<CollectionPolicyOverrideResponse> {
  return apiRequest<CollectionPolicyOverrideResponse>(
    `/admin/ai-response-policy/${encodeURIComponent(policyId)}/collections/${encodeURIComponent(collectionId)}`,
    { method: "PUT", json: payload },
  );
}

export async function deleteCollectionPolicyOverride(
  policyId: string,
  collectionId: string,
): Promise<void> {
  await apiRequest<void>(
    `/admin/ai-response-policy/${encodeURIComponent(policyId)}/collections/${encodeURIComponent(collectionId)}`,
    { method: "DELETE" },
  );
}

// ---------------------------------------------------------------------------
// API functions — policy preview
// ---------------------------------------------------------------------------

export async function previewAiResponsePolicy(
  payload: PolicyPreviewRequest,
): Promise<PolicyPreviewResponse> {
  return apiRequest<PolicyPreviewResponse>(
    "/admin/ai-response-policy/preview",
    { method: "POST", json: payload },
  );
}

// ---------------------------------------------------------------------------
// API functions — audit logs
// ---------------------------------------------------------------------------

export async function listPolicyEvaluationLogs(params?: {
  outcome?: PolicyOutcome;
  limit?: number;
  offset?: number;
}): Promise<PolicyEvaluationLogListResponse> {
  const qs = new URLSearchParams();
  if (params?.outcome) qs.set("outcome", params.outcome);
  if (params?.limit !== undefined) qs.set("limit", String(params.limit));
  if (params?.offset !== undefined) qs.set("offset", String(params.offset));
  const suffix = qs.toString() ? `?${qs}` : "";
  return apiRequest<PolicyEvaluationLogListResponse>(
    `/admin/ai-response-policy/logs${suffix}`,
  );
}
