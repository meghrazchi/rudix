import type { Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

export type ModelProviderSettingsResponse = Served<
  Schemas["ModelProviderSettingsResponse"]
>;

export type EffectiveModelProviderPolicyResponse = Served<
  Schemas["EffectiveModelProviderPolicyResponse"]
>;

export type ModelProviderChangeLogEntry = Served<
  Schemas["ModelProviderChangeLogEntryResponse"]
>;

export type ModelProviderChangeLogResponse = Served<
  Schemas["ModelProviderChangeLogResponse"]
>;

export type UpdateModelProviderSettingsRequest =
  Schemas["UpdateModelProviderSettingsRequest"];

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

export async function getModelProviderSettings(): Promise<ModelProviderSettingsResponse> {
  return apiRequest<ModelProviderSettingsResponse>("/model-provider-settings");
}

export async function updateModelProviderSettings(
  payload: UpdateModelProviderSettingsRequest,
): Promise<ModelProviderSettingsResponse> {
  return apiRequest<ModelProviderSettingsResponse>("/model-provider-settings", {
    method: "PATCH",
    json: payload,
  });
}

export async function resetModelProviderSettings(
  changeNote?: string,
): Promise<void> {
  return apiRequest<void>("/model-provider-settings", {
    method: "DELETE",
    query: changeNote ? { change_note: changeNote } : undefined,
  });
}

// ---------------------------------------------------------------------------
// Effective policy
// ---------------------------------------------------------------------------

export async function getEffectiveModelProviderPolicy(): Promise<EffectiveModelProviderPolicyResponse> {
  return apiRequest<EffectiveModelProviderPolicyResponse>(
    "/model-provider-settings/effective-policy",
  );
}

// ---------------------------------------------------------------------------
// Change log
// ---------------------------------------------------------------------------

export async function listModelProviderChangeLog(
  params: { limit?: number; offset?: number } = {},
): Promise<ModelProviderChangeLogResponse> {
  return apiRequest<ModelProviderChangeLogResponse>(
    "/model-provider-settings/change-log",
    { query: { limit: params.limit, offset: params.offset } },
  );
}
