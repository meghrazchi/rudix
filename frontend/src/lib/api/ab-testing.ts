import type { Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type AbExperimentStatus = "draft" | "running" | "completed" | "failed";
export type AbVariantApprovalStatus = "pending" | "approved" | "rejected";

export type AbVariantResponse = Served<Schemas["AbVariantResponse"]>;

export type AbExperimentResponse = Served<Schemas["AbExperimentResponse"]>;

export type AbExperimentListResponse = Served<
  Schemas["AbExperimentListResponse"]
>;

export type VariantMetricDelta = Served<Schemas["VariantMetricDelta"]>;

export type VariantRunSummary = Served<Schemas["VariantRunSummary"]>;

export type AbExperimentRunResponse = Served<
  Schemas["AbExperimentRunResponse"]
>;

export type AbExperimentRunListResponse = Served<
  Schemas["AbExperimentRunListResponse"]
>;

// ---------------------------------------------------------------------------
// Request payloads
// ---------------------------------------------------------------------------

export type CreateAbExperimentRequest = Schemas["CreateAbExperimentRequest"];

export type UpdateAbExperimentRequest = Schemas["UpdateAbExperimentRequest"];

export type CreateAbVariantRequest = Schemas["CreateAbVariantRequest"];

export type StartAbExperimentRunRequest =
  Schemas["StartAbExperimentRunRequest"];

export type ApproveVariantRequest = Schemas["ApproveVariantRequest"];

export type RejectVariantRequest = Schemas["RejectVariantRequest"];

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
  payload: CreateAbExperimentRequest,
): Promise<AbExperimentResponse> {
  return apiRequest<AbExperimentResponse>(BASE, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getAbExperiment(
  experimentId: string,
): Promise<AbExperimentResponse> {
  return apiRequest<AbExperimentResponse>(`${BASE}/${experimentId}`);
}

export async function updateAbExperiment(
  experimentId: string,
  payload: UpdateAbExperimentRequest,
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
  payload: CreateAbVariantRequest,
): Promise<AbVariantResponse> {
  return apiRequest<AbVariantResponse>(`${BASE}/${experimentId}/variants`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function removeVariant(
  experimentId: string,
  variantId: string,
): Promise<void> {
  await apiRequest<void>(`${BASE}/${experimentId}/variants/${variantId}`, {
    method: "DELETE",
  });
}

export async function startExperimentRun(
  experimentId: string,
  payload?: StartAbExperimentRunRequest,
): Promise<AbExperimentRunResponse> {
  return apiRequest<AbExperimentRunResponse>(`${BASE}/${experimentId}/runs`, {
    method: "POST",
    body: JSON.stringify(payload ?? {}),
  });
}

export async function listExperimentRuns(
  experimentId: string,
  params?: { limit?: number; offset?: number },
): Promise<AbExperimentRunListResponse> {
  const qs = new URLSearchParams();
  if (params?.limit != null) qs.set("limit", String(params.limit));
  if (params?.offset != null) qs.set("offset", String(params.offset));
  return apiRequest<AbExperimentRunListResponse>(
    `${BASE}/${experimentId}/runs?${qs}`,
  );
}

export async function getExperimentRun(
  experimentId: string,
  runId: string,
): Promise<AbExperimentRunResponse> {
  return apiRequest<AbExperimentRunResponse>(
    `${BASE}/${experimentId}/runs/${runId}`,
  );
}

export async function finalizeExperimentRun(
  experimentId: string,
  runId: string,
): Promise<AbExperimentRunResponse> {
  return apiRequest<AbExperimentRunResponse>(
    `${BASE}/${experimentId}/runs/${runId}/finalize`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

export async function approveVariant(
  experimentId: string,
  variantId: string,
  payload?: ApproveVariantRequest,
): Promise<AbVariantResponse> {
  return apiRequest<AbVariantResponse>(
    `${BASE}/${experimentId}/variants/${variantId}/approve`,
    { method: "POST", body: JSON.stringify(payload ?? {}) },
  );
}

export async function rejectVariant(
  experimentId: string,
  variantId: string,
  payload?: RejectVariantRequest,
): Promise<AbVariantResponse> {
  return apiRequest<AbVariantResponse>(
    `${BASE}/${experimentId}/variants/${variantId}/reject`,
    { method: "POST", body: JSON.stringify(payload ?? {}) },
  );
}
