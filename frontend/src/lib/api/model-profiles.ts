import { apiRequest } from "@/lib/api/request";

export type TaskType =
  | "chat"
  | "summarization"
  | "comparison"
  | "embeddings"
  | "evaluations"
  | "agentic";

export type ProfileSource = "env_default" | "org_profile" | "request_override";

export type ModelProfileResponse = {
  profile_id: string;
  organization_id: string;
  profile_name: string;
  task_type: TaskType;
  provider_type: string;
  base_model: string;
  context_window: number | null;
  max_tokens: number | null;
  temperature: number | null;
  json_mode: boolean;
  streaming: boolean;
  fallback_provider_key: string | null;
  is_active: boolean;
  is_experimental: boolean;
  cost_metadata: Record<string, unknown>;
  version: number;
  updated_by_id: string | null;
  created_at: string;
  updated_at: string;
};

export type ModelProfileListResponse = {
  items: ModelProfileResponse[];
  total: number;
};

export type ResolvedTaskProfile = {
  task_type: TaskType;
  provider_type: string;
  base_model: string;
  max_tokens: number | null;
  temperature: number | null;
  json_mode: boolean;
  streaming: boolean;
  fallback_provider_key: string | null;
  source: ProfileSource;
  version: number;
};

export type EffectiveModelPolicyResponse = {
  organization_id: string;
  profiles: ResolvedTaskProfile[];
  feature_local_llm_enabled: boolean;
  feature_local_embeddings_enabled: boolean;
  feature_fallback_enabled: boolean;
  feature_request_override_enabled: boolean;
};

export type ProfileValidationIssue = {
  field: string;
  code: string;
  message: string;
};

export type ValidateProfileResponse = {
  valid: boolean;
  issues: ProfileValidationIssue[];
};

export type UpsertModelProfileRequest = {
  profile_name: string;
  provider_type: string;
  base_model: string;
  context_window?: number | null;
  max_tokens?: number | null;
  temperature?: number | null;
  json_mode?: boolean;
  streaming?: boolean;
  fallback_provider_key?: string | null;
  is_experimental?: boolean;
  cost_metadata?: Record<string, unknown>;
  change_note?: string | null;
};

export type ValidateProfileRequest = {
  task_type: TaskType;
  provider_type: string;
  base_model: string;
  json_mode?: boolean;
  is_experimental?: boolean;
  fallback_provider_key?: string | null;
};

export async function listModelProfiles(): Promise<ModelProfileListResponse> {
  return apiRequest<ModelProfileListResponse>("/model-profiles");
}

export async function getEffectiveModelPolicy(): Promise<EffectiveModelPolicyResponse> {
  return apiRequest<EffectiveModelPolicyResponse>("/model-profiles/effective");
}

export async function getModelProfile(
  taskType: TaskType,
): Promise<ModelProfileResponse> {
  return apiRequest<ModelProfileResponse>(`/model-profiles/${taskType}`);
}

export async function upsertModelProfile(
  taskType: TaskType,
  payload: UpsertModelProfileRequest,
): Promise<ModelProfileResponse> {
  return apiRequest<ModelProfileResponse>(`/model-profiles/${taskType}`, {
    method: "PUT",
    body: JSON.stringify(payload),
    headers: { "Content-Type": "application/json" },
  });
}

export async function deleteModelProfile(
  taskType: TaskType,
  changeNote?: string,
): Promise<void> {
  const url = changeNote
    ? `/model-profiles/${taskType}?change_note=${encodeURIComponent(changeNote)}`
    : `/model-profiles/${taskType}`;
  return apiRequest<void>(url, { method: "DELETE" });
}

export async function validateModelProfile(
  payload: ValidateProfileRequest,
): Promise<ValidateProfileResponse> {
  return apiRequest<ValidateProfileResponse>("/model-profiles/validate", {
    method: "POST",
    body: JSON.stringify(payload),
    headers: { "Content-Type": "application/json" },
  });
}
