import { apiRequest } from "@/lib/api/request";

export type ModelProviderSettingsResponse = {
  organization_id: string;
  provider: string | null;
  llm_model: string | null;
  embedding_model: string | null;
  max_tokens: number | null;
  timeout_seconds: number | null;
  max_retries: number | null;
  fallback_model: string | null;
  disabled_models: string[];
  /** True when an LLM API key is configured in the environment — never the key itself */
  llm_key_configured: boolean;
  version: number;
  updated_by_id: string | null;
  updated_at: string;
};

export type EffectiveModelProviderPolicyResponse = {
  organization_id: string;
  provider: string;
  llm_model: string;
  embedding_model: string;
  max_tokens: number | null;
  timeout_seconds: number;
  max_retries: number;
  fallback_model: string | null;
  disabled_models: string[];
  llm_key_configured: boolean;
  source: "org_override" | "system_default";
  version: number;
};

export type ModelProviderChangeLogEntry = {
  entry_id: string;
  organization_id: string;
  version_number: number;
  settings_snapshot: Record<string, unknown>;
  change_note: string | null;
  changed_by_id: string | null;
  created_at: string;
};

export type ModelProviderChangeLogResponse = {
  items: ModelProviderChangeLogEntry[];
  total: number;
};

export type UpdateModelProviderSettingsRequest = {
  provider?: string | null;
  llm_model?: string | null;
  embedding_model?: string | null;
  max_tokens?: number | null;
  timeout_seconds?: number | null;
  max_retries?: number | null;
  fallback_model?: string | null;
  disabled_models?: string[] | null;
  change_note?: string | null;
};

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
