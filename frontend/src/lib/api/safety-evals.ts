import { apiRequest } from "@/lib/api/request";

export type SafetyViolationType =
  | "injection"
  | "cross_tenant_leakage"
  | "private_source_exposure"
  | "unsupported_claims"
  | "malicious_document"
  | "unsafe_transform";

export type SafetyEvalSeverity = "critical" | "high" | "medium" | "low";

export type SafetyEvalCaseResponse = {
  case_id: string;
  suite_name: string;
  violation_type: SafetyViolationType;
  name: string;
  description: string | null;
  prompt_text: string;
  severity: SafetyEvalSeverity;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type SafetyEvalCaseListResponse = {
  items: SafetyEvalCaseResponse[];
  total: number;
  limit: number;
  offset: number;
};

export type CreateSafetyEvalCaseRequest = {
  suite_name: string;
  violation_type: SafetyViolationType;
  name: string;
  prompt_text: string;
  severity?: SafetyEvalSeverity;
  description?: string | null;
  metadata?: Record<string, unknown>;
};

export type SafetyEvalRunResponse = {
  run_id: string;
  status: "queued" | "running" | "completed" | "failed";
  suite_name: string | null;
  pass_count: number | null;
  fail_count: number | null;
  total_count: number | null;
  pass_rate: number | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type SafetyEvalRunListResponse = {
  items: SafetyEvalRunResponse[];
  total: number;
  limit: number;
  offset: number;
};

export type SafetyEvalResultResponse = {
  result_id: string;
  case_id: string;
  case_name: string;
  suite_name: string;
  violation_type: string;
  severity: string;
  passed: boolean;
  violation_detected: boolean;
  violation_type_detected: string | null;
  score: number | null;
  latency_ms: number | null;
  details: Record<string, unknown>;
  created_at: string;
};

export type SafetyEvalResultListResponse = {
  items: SafetyEvalResultResponse[];
  total: number;
  limit: number;
  offset: number;
};

export type SafetyEvalRunDetailResponse = {
  run_id: string;
  status: "queued" | "running" | "completed" | "failed";
  suite_name: string | null;
  config: Record<string, unknown>;
  pass_count: number | null;
  fail_count: number | null;
  total_count: number | null;
  pass_rate: number | null;
  summary: Record<string, unknown>;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
  results: SafetyEvalResultListResponse;
};

export type TriggerSafetyEvalRunRequest = {
  suite_name?: string | null;
  model_version?: string | null;
  retrieval_settings?: Record<string, unknown>;
  regression_threshold?: number | null;
};

export type TriggerSafetyEvalRunResponse = {
  run_id: string;
  status: string;
  message: string;
};

export type SafetyEvalReportResponse = {
  run_id: string;
  status: string;
  generated_at: string;
  suite_name: string | null;
  total_cases: number;
  pass_count: number;
  fail_count: number;
  pass_rate: number;
  baseline_pass_rate: number | null;
  regression_detected: boolean;
  regression_threshold: number | null;
  by_violation_type: Record<string, Record<string, unknown>>;
  by_severity: Record<string, Record<string, unknown>>;
  failed_cases: Array<Record<string, unknown>>;
  summary: Record<string, unknown>;
};

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
