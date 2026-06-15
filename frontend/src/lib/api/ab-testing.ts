import { apiRequest } from "@/lib/api/request";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type AbExperimentStatus = "draft" | "running" | "completed" | "failed";
export type AbVariantApprovalStatus = "pending" | "approved" | "rejected";

export type AbVariantResponse = {
  variant_id: string;
  experiment_id: string;
  label: string;
  description: string | null;
  rag_profile_id: string | null;
  rag_profile_version: number | null;
  prompt_template_version_id: string | null;
  model_profile_key: string | null;
  config_snapshot: Record<string, unknown>;
  approval_status: AbVariantApprovalStatus;
  approved_by_id: string | null;
  approval_note: string | null;
  approved_at: string | null;
  created_at: string;
  updated_at: string;
};

export type AbExperimentResponse = {
  experiment_id: string;
  name: string;
  description: string | null;
  evaluation_set_id: string;
  status: AbExperimentStatus;
  metrics_config: Record<string, unknown>;
  created_by_id: string | null;
  created_at: string;
  updated_at: string;
  variants: AbVariantResponse[];
};

export type AbExperimentListResponse = {
  items: AbExperimentResponse[];
  total: number;
  limit: number;
  offset: number;
};

export type VariantMetricDelta = {
  metric: string;
  label: string;
  reference_value: number | null;
  variant_value: number | null;
  delta: number | null;
  improved: boolean | null;
};

export type VariantRunSummary = {
  variant_id: string;
  variant_label: string;
  evaluation_run_id: string | null;
  status: string;
  metrics_summary: Record<string, number | null>;
  deltas_vs_reference: VariantMetricDelta[];
  error_detail: string | null;
};

export type AbExperimentRunResponse = {
  experiment_run_id: string;
  experiment_id: string;
  status: AbExperimentStatus;
  triggered_by_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
  variant_summaries: VariantRunSummary[];
  comparison_report: Record<string, unknown>;
};

export type AbExperimentRunListResponse = {
  items: AbExperimentRunResponse[];
  total: number;
  limit: number;
  offset: number;
};

// ---------------------------------------------------------------------------
// Request payloads
// ---------------------------------------------------------------------------

export type CreateAbExperimentRequest = {
  name: string;
  description?: string | null;
  evaluation_set_id: string;
  metrics_config?: Record<string, unknown>;
};

export type UpdateAbExperimentRequest = {
  name?: string | null;
  description?: string | null;
  metrics_config?: Record<string, unknown> | null;
};

export type CreateAbVariantRequest = {
  label: string;
  description?: string | null;
  rag_profile_id?: string | null;
  rag_profile_version?: number | null;
  prompt_template_version_id?: string | null;
  model_profile_key?: string | null;
  config_snapshot?: Record<string, unknown>;
};

export type StartAbExperimentRunRequest = {
  note?: string | null;
};

export type ApproveVariantRequest = {
  note?: string | null;
  set_as_default_profile?: boolean;
};

export type RejectVariantRequest = {
  note?: string | null;
};

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

const BASE = "/ab-experiments";

export async function listAbExperiments(params?: {
  limit?: number;
  offset?: number;
}): Promise<AbExperimentListResponse> {
  const qs = new URLSearchParams();
  if (params?.limit != null) qs.set("limit", String(params.limit));
  if (params?.offset != null) qs.set("offset", String(params.offset));
  return apiRequest<AbExperimentListResponse>(`${BASE}?${qs}`);
}

export async function createAbExperiment(
  payload: CreateAbExperimentRequest
): Promise<AbExperimentResponse> {
  return apiRequest<AbExperimentResponse>(BASE, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getAbExperiment(experimentId: string): Promise<AbExperimentResponse> {
  return apiRequest<AbExperimentResponse>(`${BASE}/${experimentId}`);
}

export async function updateAbExperiment(
  experimentId: string,
  payload: UpdateAbExperimentRequest
): Promise<AbExperimentResponse> {
  return apiRequest<AbExperimentResponse>(`${BASE}/${experimentId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deleteAbExperiment(experimentId: string): Promise<void> {
  await apiRequest<void>(`${BASE}/${experimentId}`, { method: "DELETE" });
}

export async function addVariant(
  experimentId: string,
  payload: CreateAbVariantRequest
): Promise<AbVariantResponse> {
  return apiRequest<AbVariantResponse>(`${BASE}/${experimentId}/variants`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function removeVariant(experimentId: string, variantId: string): Promise<void> {
  await apiRequest<void>(`${BASE}/${experimentId}/variants/${variantId}`, { method: "DELETE" });
}

export async function startExperimentRun(
  experimentId: string,
  payload?: StartAbExperimentRunRequest
): Promise<AbExperimentRunResponse> {
  return apiRequest<AbExperimentRunResponse>(`${BASE}/${experimentId}/runs`, {
    method: "POST",
    body: JSON.stringify(payload ?? {}),
  });
}

export async function listExperimentRuns(
  experimentId: string,
  params?: { limit?: number; offset?: number }
): Promise<AbExperimentRunListResponse> {
  const qs = new URLSearchParams();
  if (params?.limit != null) qs.set("limit", String(params.limit));
  if (params?.offset != null) qs.set("offset", String(params.offset));
  return apiRequest<AbExperimentRunListResponse>(
    `${BASE}/${experimentId}/runs?${qs}`
  );
}

export async function getExperimentRun(
  experimentId: string,
  runId: string
): Promise<AbExperimentRunResponse> {
  return apiRequest<AbExperimentRunResponse>(`${BASE}/${experimentId}/runs/${runId}`);
}

export async function finalizeExperimentRun(
  experimentId: string,
  runId: string
): Promise<AbExperimentRunResponse> {
  return apiRequest<AbExperimentRunResponse>(
    `${BASE}/${experimentId}/runs/${runId}/finalize`,
    { method: "POST", body: JSON.stringify({}) }
  );
}

export async function approveVariant(
  experimentId: string,
  variantId: string,
  payload?: ApproveVariantRequest
): Promise<AbVariantResponse> {
  return apiRequest<AbVariantResponse>(
    `${BASE}/${experimentId}/variants/${variantId}/approve`,
    { method: "POST", body: JSON.stringify(payload ?? {}) }
  );
}

export async function rejectVariant(
  experimentId: string,
  variantId: string,
  payload?: RejectVariantRequest
): Promise<AbVariantResponse> {
  return apiRequest<AbVariantResponse>(
    `${BASE}/${experimentId}/variants/${variantId}/reject`,
    { method: "POST", body: JSON.stringify(payload ?? {}) }
  );
}
