import type { Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

export type SafetyViolationType =
  | "injection"
  | "cross_tenant_leakage"
  | "private_source_exposure"
  | "unsupported_claims"
  | "malicious_document"
  | "unsafe_transform";

export type SafetyEvalSeverity = "critical" | "high" | "medium" | "low";

export type SafetyEvalCaseResponse = Served<Schemas["SafetyEvalCaseResponse"]>;

export type SafetyEvalCaseListResponse = Served<
  Schemas["SafetyEvalCaseListResponse"]
>;

export type CreateSafetyEvalCaseRequest =
  Schemas["CreateSafetyEvalCaseRequest"];

export type SafetyEvalRunResponse = Served<Schemas["SafetyEvalRunResponse"]>;

export type SafetyEvalRunListResponse = Served<
  Schemas["SafetyEvalRunListResponse"]
>;

export type SafetyEvalResultResponse = Served<
  Schemas["SafetyEvalResultResponse"]
>;

export type SafetyEvalResultListResponse = Served<
  Schemas["SafetyEvalResultListResponse"]
>;

export type SafetyEvalRunDetailResponse = Served<
  Schemas["SafetyEvalRunDetailResponse"]
>;

export type TriggerSafetyEvalRunRequest =
  Schemas["TriggerSafetyEvalRunRequest"];

export type TriggerSafetyEvalRunResponse = Served<
  Schemas["TriggerSafetyEvalRunResponse"]
>;

export type SafetyEvalReportResponse = Served<
  Schemas["SafetyEvalReportResponse"]
>;

export async function createSafetyEvalCase(
  payload: CreateSafetyEvalCaseRequest,
): Promise<SafetyEvalCaseResponse> {
  return apiRequest<SafetyEvalCaseResponse>("/safety-evals/cases", {
    method: "POST",
    json: payload,
  });
}

export async function listSafetyEvalCases(
  params: {
    suite_name?: string;
    violation_type?: string;
    limit?: number;
    offset?: number;
  } = {},
): Promise<SafetyEvalCaseListResponse> {
  return apiRequest<SafetyEvalCaseListResponse>("/safety-evals/cases", {
    query: {
      suite_name: params.suite_name,
      violation_type: params.violation_type,
      limit: params.limit,
      offset: params.offset,
    },
  });
}

export async function triggerSafetyEvalRun(
  payload: TriggerSafetyEvalRunRequest,
): Promise<TriggerSafetyEvalRunResponse> {
  return apiRequest<TriggerSafetyEvalRunResponse>("/safety-evals/runs", {
    method: "POST",
    json: payload,
  });
}

export async function listSafetyEvalRuns(
  params: { suite_name?: string; limit?: number; offset?: number } = {},
): Promise<SafetyEvalRunListResponse> {
  return apiRequest<SafetyEvalRunListResponse>("/safety-evals/runs", {
    query: {
      suite_name: params.suite_name,
      limit: params.limit,
      offset: params.offset,
    },
  });
}

export async function getSafetyEvalRunDetail(
  runId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<SafetyEvalRunDetailResponse> {
  return apiRequest<SafetyEvalRunDetailResponse>(
    `/safety-evals/runs/${encodeURIComponent(runId)}`,
    {
      query: {
        limit: params.limit,
        offset: params.offset,
      },
    },
  );
}

export async function getSafetyEvalReport(
  runId: string,
): Promise<SafetyEvalReportResponse> {
  return apiRequest<SafetyEvalReportResponse>(
    `/safety-evals/runs/${encodeURIComponent(runId)}/report`,
  );
}
