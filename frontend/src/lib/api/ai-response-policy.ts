import { apiRequest } from "@/lib/api/request";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type CitationMode = "required" | "recommended" | "disabled";
export type NoAnswerBehavior = "refuse" | "warn" | "allow";
export type StaleSourceBehavior = "warn" | "refuse" | "ignore";
export type DisclaimerPosition = "prepend" | "append";
export type PolicyOutcome = "allowed" | "blocked" | "warned";
export type PolicySource = "org" | "collection" | "none";

export type AiResponsePolicyResponse = {
  policy_id: string;
  organization_id: string;
  policy_name: string;
  description: string | null;
  is_active: boolean;
  citation_mode: CitationMode;
  min_confidence_threshold: number | null;
  no_answer_behavior: NoAnswerBehavior;
  stale_source_behavior: StaleSourceBehavior;
  blocked_topics: string[];
  allowed_topics: string[] | null;
  min_sources_required: number | null;
  disclaimer_text: string | null;
  disclaimer_position: DisclaimerPosition;
  refusal_message: string | null;
  created_by_id: string | null;
  updated_by_id: string | null;
  created_at: string;
  updated_at: string;
};

export type AiResponsePolicyListResponse = {
  items: AiResponsePolicyResponse[];
  total: number;
};

export type CreateAiResponsePolicyRequest = {
  policy_name: string;
  description?: string | null;
  citation_mode?: CitationMode;
  min_confidence_threshold?: number | null;
  no_answer_behavior?: NoAnswerBehavior;
  stale_source_behavior?: StaleSourceBehavior;
  blocked_topics?: string[];
  allowed_topics?: string[] | null;
  min_sources_required?: number | null;
  disclaimer_text?: string | null;
  disclaimer_position?: DisclaimerPosition;
  refusal_message?: string | null;
};

export type UpdateAiResponsePolicyRequest = {
  policy_name?: string;
  description?: string | null;
  citation_mode?: CitationMode;
  min_confidence_threshold?: number | null;
  no_answer_behavior?: NoAnswerBehavior;
  stale_source_behavior?: StaleSourceBehavior;
  blocked_topics?: string[];
  allowed_topics?: string[] | null;
  min_sources_required?: number | null;
  disclaimer_text?: string | null;
  disclaimer_position?: DisclaimerPosition;
  refusal_message?: string | null;
  is_active?: boolean;
};

export type CollectionPolicyOverrideResponse = {
  override_id: string;
  org_policy_id: string;
  collection_id: string;
  citation_mode: CitationMode | null;
  min_confidence_threshold: number | null;
  no_answer_behavior: NoAnswerBehavior | null;
  stale_source_behavior: StaleSourceBehavior | null;
  blocked_topics: string[] | null;
  allowed_topics: string[] | null;
  min_sources_required: number | null;
  disclaimer_text: string | null;
  refusal_message: string | null;
  updated_by_id: string | null;
  created_at: string;
  updated_at: string;
};

export type UpsertCollectionPolicyOverrideRequest = {
  citation_mode?: CitationMode | null;
  min_confidence_threshold?: number | null;
  no_answer_behavior?: NoAnswerBehavior | null;
  stale_source_behavior?: StaleSourceBehavior | null;
  blocked_topics?: string[] | null;
  allowed_topics?: string[] | null;
  min_sources_required?: number | null;
  disclaimer_text?: string | null;
  refusal_message?: string | null;
};

export type PolicyPreviewRequest = {
  question: string;
  confidence_score?: number;
  citation_count?: number;
  stale_source_count?: number;
  collection_id?: string | null;
  policy_id?: string | null;
};

export type PolicyPreviewResponse = {
  outcome: PolicyOutcome;
  policy_source: PolicySource;
  policy_id: string | null;
  violated_rules: string[];
  warning_flags: string[];
  refusal_message: string | null;
  disclaimer_text: string | null;
  disclaimer_position: DisclaimerPosition;
};

export type PolicyEvaluationLogResponse = {
  log_id: string;
  organization_id: string;
  user_id: string | null;
  org_policy_id: string | null;
  collection_id: string | null;
  chat_session_id: string | null;
  chat_message_id: string | null;
  outcome: PolicyOutcome;
  policy_source: PolicySource;
  violated_rules: string[];
  warning_flags: string[];
  question_preview: string | null;
  confidence_score: number | null;
  citation_count: number | null;
  stale_source_count: number | null;
  is_preview_run: boolean;
  created_at: string;
};

export type PolicyEvaluationLogListResponse = {
  items: PolicyEvaluationLogResponse[];
  total: number;
  limit: number;
  offset: number;
};

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
