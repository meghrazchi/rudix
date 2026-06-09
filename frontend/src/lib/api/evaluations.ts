import { apiRequest } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/schema";
import type { ChunkingProfileConfigInput } from "@/lib/schemas/chunking-profiles";

type Schemas = components["schemas"];

export type EvaluationSetResponse = Omit<
  Schemas["EvaluationSetResponse"],
  "status" | "version" | "owner_id" | "scope"
> & {
  status: string;
  version: number;
  owner_id?: string | null;
  scope: Record<string, unknown>;
};
export type EvaluationSetListResponse = {
  items: EvaluationSetResponse[];
  total: number;
  limit: number;
  offset: number;
};
export type CreateEvaluationSetRequest = Schemas["CreateEvaluationSetRequest"];
export type EvaluationQuestionResponse = Omit<
  Schemas["EvaluationQuestionResponse"],
  "tags" | "difficulty" | "owner_id"
> & {
  tags: string[];
  difficulty?: string | null;
  owner_id?: string | null;
};
export type EvaluationQuestionListResponse = {
  evaluation_set_id: string;
  items: EvaluationQuestionResponse[];
  total: number;
  limit: number;
  offset: number;
};
export type CreateEvaluationQuestionRequest =
  Schemas["CreateEvaluationQuestionRequest"];
type BaseEvaluationRunConfig = Schemas["EvaluationRunConfig"];
type BaseRunEvaluationRequest = Schemas["RunEvaluationRequest"];
export type RunEvaluationResponse = Schemas["RunEvaluationResponse"];
export type EvaluationRunResultResponse =
  Schemas["EvaluationRunResultResponse"];
export type EvaluationRunDetailResponse =
  Schemas["EvaluationRunDetailResponse"];

export type EvaluationChunkingComparisonTarget = {
  label?: string | null;
  chunking_profile_id?: string | null;
  chunking_profile_config?: ChunkingProfileConfigInput | null;
};

export type EvaluationRegressionThresholds = {
  retrieval_hit_rate_min?: number | null;
  citation_accuracy_score_min?: number | null;
  faithfulness_score_min?: number | null;
  max_not_found_rate?: number | null;
};

export type EvaluationRunConfig = Omit<
  BaseEvaluationRunConfig,
  | "chunking_profile_id"
  | "chunking_profile_config"
  | "comparison_targets"
  | "regression_thresholds"
  | "run_name"
> & {
  run_name?: string | null;
  chunking_profile_id?: string | null;
  chunking_profile_config?: ChunkingProfileConfigInput | null;
  comparison_targets?: EvaluationChunkingComparisonTarget[];
  regression_thresholds?: EvaluationRegressionThresholds | null;
  /** UUID of an OrgModelProfile to use for this run. When omitted the org's evaluations task profile is resolved at runtime. */
  model_profile_id?: string | null;
};

export type RunEvaluationRequest = Omit<BaseRunEvaluationRequest, "config"> & {
  config?: EvaluationRunConfig;
};

export type UpdateEvaluationSetRequest = {
  name?: string | null;
  description?: string | null;
  scope?: Record<string, unknown> | null;
};

export type UpdateEvaluationQuestionRequest = {
  question?: string | null;
  expected_answer?: string | null;
  expected_document_id?: string | null;
  expected_page_number?: number | null;
  difficulty?: "easy" | "medium" | "hard" | null;
  tags?: string[] | null;
  metadata?: Record<string, unknown> | null;
};

export type ImportCasesRequest = {
  format: "json" | "csv";
  data: string;
  skip_duplicates?: boolean;
};

export type ImportCasesResponse = {
  imported: number;
  skipped_duplicates: number;
  validation_errors: string[];
};

export type PublishDatasetResponse = {
  evaluation_set_id: string;
  version_number: number;
  question_count: number;
  status: "published";
};

export type DuplicateDatasetResponse = {
  evaluation_set_id: string;
  name: string;
  question_count: number;
  status: "draft";
  created_at: string;
};

export type DatasetValidationIssue = {
  evaluation_question_id: string;
  question_preview: string;
  issue_type:
    | "missing_scope"
    | "deleted_source"
    | "inaccessible_document"
    | "no_expected_answer"
    | "duplicate";
  detail: string;
};

export type ValidateDatasetResponse = {
  evaluation_set_id: string;
  is_valid: boolean;
  issue_count: number;
  issues: DatasetValidationIssue[];
};

export type EvaluationDatasetVersionResponse = {
  version_id: string;
  evaluation_set_id: string;
  version_number: number;
  question_count: number;
  published_by_id: string | null;
  published_at: string | null;
  created_at: string;
};

export type EvaluationDatasetVersionListResponse = {
  evaluation_set_id: string;
  items: EvaluationDatasetVersionResponse[];
  total: number;
};

export type ConvertFeedbackToCasesRequest = {
  evaluation_set_id: string;
  feedback_ids: string[];
  default_difficulty?: "easy" | "medium" | "hard" | null;
};

export type ConvertFeedbackToCasesResponse = {
  created: number;
  skipped: number;
  evaluation_set_id: string;
};

export async function createEvaluationSet(
  payload: CreateEvaluationSetRequest,
): Promise<EvaluationSetResponse> {
  return apiRequest<EvaluationSetResponse>("/evaluation-sets", {
    method: "POST",
    json: payload,
  });
}

export async function listEvaluationSets(
  params: { limit?: number; offset?: number } = {},
): Promise<EvaluationSetListResponse> {
  return apiRequest<EvaluationSetListResponse>("/evaluation-sets", {
    query: {
      limit: params.limit,
      offset: params.offset,
    },
  });
}

export async function updateEvaluationSet(
  evaluationSetId: string,
  payload: UpdateEvaluationSetRequest,
): Promise<EvaluationSetResponse> {
  return apiRequest<EvaluationSetResponse>(
    `/evaluation-sets/${encodeURIComponent(evaluationSetId)}`,
    {
      method: "PATCH",
      json: payload,
    },
  );
}

export async function deleteEvaluationSet(
  evaluationSetId: string,
): Promise<void> {
  return apiRequest<void>(
    `/evaluation-sets/${encodeURIComponent(evaluationSetId)}`,
    { method: "DELETE" },
  );
}

export async function publishEvaluationSet(
  evaluationSetId: string,
): Promise<PublishDatasetResponse> {
  return apiRequest<PublishDatasetResponse>(
    `/evaluation-sets/${encodeURIComponent(evaluationSetId)}/publish`,
    { method: "POST" },
  );
}

export async function duplicateEvaluationSet(
  evaluationSetId: string,
): Promise<DuplicateDatasetResponse> {
  return apiRequest<DuplicateDatasetResponse>(
    `/evaluation-sets/${encodeURIComponent(evaluationSetId)}/duplicate`,
    { method: "POST" },
  );
}

export async function importEvaluationCases(
  evaluationSetId: string,
  payload: ImportCasesRequest,
): Promise<ImportCasesResponse> {
  return apiRequest<ImportCasesResponse>(
    `/evaluation-sets/${encodeURIComponent(evaluationSetId)}/import`,
    {
      method: "POST",
      json: payload,
    },
  );
}

export async function validateEvaluationDataset(
  evaluationSetId: string,
): Promise<ValidateDatasetResponse> {
  return apiRequest<ValidateDatasetResponse>(
    `/evaluation-sets/${encodeURIComponent(evaluationSetId)}/validate`,
  );
}

export async function listDatasetVersions(
  evaluationSetId: string,
): Promise<EvaluationDatasetVersionListResponse> {
  return apiRequest<EvaluationDatasetVersionListResponse>(
    `/evaluation-sets/${encodeURIComponent(evaluationSetId)}/versions`,
  );
}

export async function convertFeedbackToCases(
  payload: ConvertFeedbackToCasesRequest,
): Promise<ConvertFeedbackToCasesResponse> {
  return apiRequest<ConvertFeedbackToCasesResponse>(
    "/evaluation-sets/from-feedback",
    {
      method: "POST",
      json: payload,
    },
  );
}

export async function createEvaluationQuestion(
  evaluationSetId: string,
  payload: CreateEvaluationQuestionRequest,
): Promise<EvaluationQuestionResponse> {
  return apiRequest<EvaluationQuestionResponse>(
    `/evaluation-sets/${encodeURIComponent(evaluationSetId)}/questions`,
    {
      method: "POST",
      json: payload,
    },
  );
}

export async function listEvaluationQuestions(
  evaluationSetId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<EvaluationQuestionListResponse> {
  return apiRequest<EvaluationQuestionListResponse>(
    `/evaluation-sets/${encodeURIComponent(evaluationSetId)}/questions`,
    {
      query: {
        limit: params.limit,
        offset: params.offset,
      },
    },
  );
}

export async function updateEvaluationQuestion(
  evaluationSetId: string,
  evaluationQuestionId: string,
  payload: UpdateEvaluationQuestionRequest,
): Promise<EvaluationQuestionResponse> {
  return apiRequest<EvaluationQuestionResponse>(
    `/evaluation-sets/${encodeURIComponent(evaluationSetId)}/questions/${encodeURIComponent(evaluationQuestionId)}`,
    {
      method: "PATCH",
      json: payload,
    },
  );
}

export async function deleteEvaluationQuestion(
  evaluationSetId: string,
  evaluationQuestionId: string,
): Promise<void> {
  return apiRequest<void>(
    `/evaluation-sets/${encodeURIComponent(evaluationSetId)}/questions/${encodeURIComponent(evaluationQuestionId)}`,
    { method: "DELETE" },
  );
}

export async function runEvaluation(
  payload: RunEvaluationRequest,
): Promise<RunEvaluationResponse> {
  return apiRequest<RunEvaluationResponse>("/evaluations/run", {
    method: "POST",
    json: payload,
  });
}

export async function getEvaluationRun(
  evaluationRunId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<EvaluationRunDetailResponse> {
  return apiRequest<EvaluationRunDetailResponse>(
    `/evaluations/runs/${encodeURIComponent(evaluationRunId)}`,
    {
      query: {
        limit: params.limit,
        offset: params.offset,
      },
    },
  );
}

export type EvaluationRunSummaryResponse = {
  evaluation_run_id: string;
  evaluation_set_id: string;
  run_name: string | null;
  status: string;
  summary: Record<string, unknown> | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type EvaluationRunListResponse = {
  items: EvaluationRunSummaryResponse[];
  total: number;
  limit: number;
  offset: number;
};

export type MetricDelta = {
  metric: string;
  label: string;
  run_a_value: number | null;
  run_b_value: number | null;
  delta: number | null;
  is_regression: boolean;
  is_improvement: boolean;
};

export type CaseComparisonRow = {
  evaluation_question_id: string;
  question: string;
  difficulty: string | null;
  tags: string[];
  run_a: EvaluationRunResultResponse | null;
  run_b: EvaluationRunResultResponse | null;
  regression: boolean;
  improvement: boolean;
};

export type RunComparisonResponse = {
  run_a: EvaluationRunSummaryResponse;
  run_b: EvaluationRunSummaryResponse;
  metric_deltas: MetricDelta[];
  regression_count: number;
  improvement_count: number;
  cases: CaseComparisonRow[];
  total_cases: number;
  filters_applied: Record<string, unknown>;
};

export type CompareRunsParams = {
  difficulty?: string | null;
  tags?: string | null;
  case_status?: "all" | "regression" | "improvement" | "failed_any";
  failure_type?: string | null;
};

export async function listEvaluationRuns(
  params: {
    evaluation_set_id?: string;
    status?: string;
    limit?: number;
    offset?: number;
  } = {},
): Promise<EvaluationRunListResponse> {
  return apiRequest<EvaluationRunListResponse>("/evaluations/runs", {
    query: {
      evaluation_set_id: params.evaluation_set_id,
      status: params.status,
      limit: params.limit,
      offset: params.offset,
    },
  });
}

export async function compareEvaluationRuns(
  runAId: string,
  runBId: string,
  params: CompareRunsParams = {},
): Promise<RunComparisonResponse> {
  return apiRequest<RunComparisonResponse>("/evaluations/compare", {
    query: {
      run_a: runAId,
      run_b: runBId,
      difficulty: params.difficulty ?? undefined,
      tags: params.tags ?? undefined,
      case_status: params.case_status,
      failure_type: params.failure_type ?? undefined,
    },
  });
}

export function buildComparisonExportUrl(
  runAId: string,
  runBId: string,
  format: "csv" | "json" = "csv",
): string {
  const params = new URLSearchParams({
    run_a: runAId,
    run_b: runBId,
    format,
  });
  return `/api/v1/evaluations/compare/export?${params.toString()}`;
}
