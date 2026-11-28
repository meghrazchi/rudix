import type { Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

export type QualityGateVerdict = "passed" | "failed" | "overridden";

export type QualityGateThresholds = Schemas["QualityGateThresholds"];

export type QualityGateResponse = Served<Schemas["QualityGateResponse"]>;

export type QualityGateListResponse = Served<
  Schemas["QualityGateListResponse"]
>;

export type GateCheckResult = Served<Schemas["GateCheckResult"]>;

export type QualityGateRunResponse = Served<Schemas["QualityGateRunResponse"]>;

export type QualityGateRunListResponse = Served<
  Schemas["QualityGateRunListResponse"]
>;

export type QualityGateReportResponse = Served<
  Schemas["QualityGateReportResponse"]
>;

export type CreateQualityGateRequest = Schemas["CreateQualityGateRequest"];

export type UpdateQualityGateRequest = Schemas["UpdateQualityGateRequest"];

export type TriggerQualityGateRunRequest =
  Schemas["TriggerQualityGateRunRequest"];

export type QualityGateOverrideRequest = Schemas["QualityGateOverrideRequest"];

export async function listQualityGates(
  params: { limit?: number; offset?: number } = {},
): Promise<QualityGateListResponse> {
  return apiRequest<QualityGateListResponse>("/quality-gates", {
    query: { limit: params.limit, offset: params.offset },
  });
}

export async function createQualityGate(
  payload: CreateQualityGateRequest,
): Promise<QualityGateResponse> {
  return apiRequest<QualityGateResponse>("/quality-gates", {
    method: "POST",
    json: payload,
  });
}

export async function getQualityGate(
  gateId: string,
): Promise<QualityGateResponse> {
  return apiRequest<QualityGateResponse>(
    `/quality-gates/${encodeURIComponent(gateId)}`,
  );
}

export async function updateQualityGate(
  gateId: string,
  payload: UpdateQualityGateRequest,
): Promise<QualityGateResponse> {
  return apiRequest<QualityGateResponse>(
    `/quality-gates/${encodeURIComponent(gateId)}`,
    { method: "PATCH", json: payload },
  );
}

export async function deleteQualityGate(gateId: string): Promise<void> {
  return apiRequest<void>(`/quality-gates/${encodeURIComponent(gateId)}`, {
    method: "DELETE",
  });
}

export async function triggerQualityGateRun(
  gateId: string,
  payload: TriggerQualityGateRunRequest,
): Promise<QualityGateRunResponse> {
  return apiRequest<QualityGateRunResponse>(
    `/quality-gates/${encodeURIComponent(gateId)}/runs`,
    { method: "POST", json: payload },
  );
}

export async function listQualityGateRuns(
  gateId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<QualityGateRunListResponse> {
  return apiRequest<QualityGateRunListResponse>(
    `/quality-gates/${encodeURIComponent(gateId)}/runs`,
    { query: { limit: params.limit, offset: params.offset } },
  );
}

export async function getQualityGateRun(
  gateRunId: string,
): Promise<QualityGateRunResponse> {
  return apiRequest<QualityGateRunResponse>(
    `/quality-gates/runs/${encodeURIComponent(gateRunId)}`,
  );
}

export async function getQualityGateReport(
  gateRunId: string,
): Promise<QualityGateReportResponse> {
  return apiRequest<QualityGateReportResponse>(
    `/quality-gates/runs/${encodeURIComponent(gateRunId)}/report`,
  );
}

export async function overrideQualityGateRun(
  gateRunId: string,
  payload: QualityGateOverrideRequest,
): Promise<QualityGateRunResponse> {
  return apiRequest<QualityGateRunResponse>(
    `/quality-gates/runs/${encodeURIComponent(gateRunId)}/override`,
    { method: "POST", json: payload },
  );
}
