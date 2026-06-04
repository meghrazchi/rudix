import { apiRequest } from "@/lib/api/request";

export type QualityGateVerdict = "passed" | "failed" | "overridden";

export type QualityGateThresholds = {
  retrieval_hit_rate_min?: number | null;
  citation_accuracy_score_min?: number | null;
  faithfulness_score_min?: number | null;
  answer_relevance_score_min?: number | null;
  not_found_rate_max?: number | null;
  safety_pass_rate_min?: number | null;
  latency_ms_p95_max?: number | null;
  cost_usd_per_question_max?: number | null;
};

export type QualityGateResponse = {
  quality_gate_id: string;
  name: string;
  description: string | null;
  thresholds: Record<string, number | null>;
  baseline_evaluation_run_id: string | null;
  baseline_safety_run_id: string | null;
  created_by_id: string | null;
  created_at: string;
  updated_at: string;
};

export type QualityGateListResponse = {
  items: QualityGateResponse[];
  total: number;
  limit: number;
  offset: number;
};

export type GateCheckResult = {
  metric: string;
  label: string;
  threshold: number;
  actual: number | null;
  passed: boolean;
  detail: string | null;
};

export type QualityGateRunResponse = {
  gate_run_id: string;
  quality_gate_id: string;
  evaluation_run_id: string | null;
  safety_eval_run_id: string | null;
  verdict: QualityGateVerdict;
  passed_checks: GateCheckResult[];
  failed_checks: GateCheckResult[];
  override_reason: string | null;
  overridden_by_id: string | null;
  overridden_at: string | null;
  created_at: string;
  updated_at: string;
};

export type QualityGateRunListResponse = {
  items: QualityGateRunResponse[];
  total: number;
  limit: number;
  offset: number;
};

export type QualityGateReportResponse = {
  gate_run_id: string;
  quality_gate_id: string;
  quality_gate_name: string;
  verdict: string;
  generated_at: string;
  evaluation_run_id: string | null;
  safety_eval_run_id: string | null;
  thresholds_applied: Record<string, number | null>;
  passed_checks: GateCheckResult[];
  failed_checks: GateCheckResult[];
  total_checks: number;
  pass_count: number;
  fail_count: number;
  override_reason: string | null;
  overridden_by_id: string | null;
  overridden_at: string | null;
  evaluation_summary: Record<string, unknown> | null;
  safety_summary: Record<string, unknown> | null;
  ci_exit_code: number;
};

export type CreateQualityGateRequest = {
  name: string;
  description?: string | null;
  thresholds?: QualityGateThresholds;
  baseline_evaluation_run_id?: string | null;
  baseline_safety_run_id?: string | null;
};

export type UpdateQualityGateRequest = {
  name?: string | null;
  description?: string | null;
  thresholds?: QualityGateThresholds | null;
  baseline_evaluation_run_id?: string | null;
  baseline_safety_run_id?: string | null;
};

export type TriggerQualityGateRunRequest = {
  evaluation_run_id?: string | null;
  safety_eval_run_id?: string | null;
};

export type QualityGateOverrideRequest = {
  reason: string;
};

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

export async function getQualityGate(gateId: string): Promise<QualityGateResponse> {
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
