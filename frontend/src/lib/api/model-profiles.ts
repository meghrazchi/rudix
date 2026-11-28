import type { Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

export type TaskType = Served<Schemas["TaskType"]>;

export type ProfileSource = Served<Schemas["ProfileSource"]>;

export type ModelProfileResponse = Served<Schemas["ModelProfileResponse"]>;

export type ModelProfileListResponse = Served<
  Schemas["ModelProfileListResponse"]
>;

export type ResolvedTaskProfile = Served<Schemas["ResolvedTaskProfile"]>;

export type EffectiveModelPolicyResponse = Served<
  Schemas["EffectiveModelPolicyResponse"]
>;

export type ProfileValidationIssue = Served<Schemas["ProfileValidationIssue"]>;

export type ValidateProfileResponse = Served<
  Schemas["ValidateProfileResponse"]
>;

export type UpsertModelProfileRequest = Schemas["UpsertModelProfileRequest"];

export type ValidateProfileRequest = Schemas["ValidateProfileRequest"];

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
