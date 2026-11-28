import type { Overlay, Served, WithOptional } from "@/lib/api/schema-helpers";
import { apiRequest } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/schema";
import type { ChunkingProfileConfigInput } from "@/lib/schemas/chunking-profiles";

type Schemas = components["schemas"];

export type EvalLanguageCode = "en" | "de" | "es" | "fr";

export type EvaluationSetResponse = Omit<
  Schemas["EvaluationSetResponse"],
  "status" | "version" | "owner_id" | "scope"
> & {
  status: string;
  version: number;
  owner_id?: string | null;
  scope: Record<string, unknown>;
};
export type EvaluationSetListResponse = Overlay<
  Served<Schemas["EvaluationSetListResponse"]>,
  { items: EvaluationSetResponse[] }
>;
export type CreateEvaluationSetRequest = Schemas["CreateEvaluationSetRequest"];
export type EvaluationQuestionResponse = Omit<
  Schemas["EvaluationQuestionResponse"],
  "tags" | "difficulty" | "owner_id"
> & {
  tags: string[];
  difficulty?: string | null;
  owner_id?: string | null;
  question_language?: string | null;
  expected_answer_language?: string | null;
  source_language?: string | null;
  translation_notes?: string | null;
};
export type EvaluationQuestionListResponse = Overlay<
  Served<Schemas["EvaluationQuestionListResponse"]>,
  { items: EvaluationQuestionResponse[] }
>;
export type CreateEvaluationQuestionRequest = Omit<
  Schemas["CreateEvaluationQuestionRequest"],
  | "question_language"
  | "expected_answer_language"
  | "source_language"
  | "translation_notes"
> & {
  question_language?: EvalLanguageCode | null;
  expected_answer_language?: EvalLanguageCode | null;
  source_language?: EvalLanguageCode | null;
  translation_notes?: string | null;
};
type BaseEvaluationRunConfig = Schemas["EvaluationRunConfig"];
type BaseRunEvaluationRequest = Schemas["RunEvaluationRequest"];
export type RunEvaluationResponse = Schemas["RunEvaluationResponse"];
export type EvaluationRunResultResponse = Omit<
  Schemas["EvaluationRunResultResponse"],
  "detected_answer_language" | "language_match_score"
> & {
  detected_answer_language?: string | null;
  language_match_score?: number | null;
};
export type EvaluationRunDetailResponse =
  Schemas["EvaluationRunDetailResponse"];

export type EvaluationChunkingComparisonTarget = {
  label?: string | null;
  chunking_profile_id?: string | null;
  chunking_profile_config?: ChunkingProfileConfigInput | null;
};

export type EvaluationRegressionThresholds =
  Schemas["EvaluationRegressionThresholds"];

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

export type UpdateEvaluationSetRequest = Schemas["UpdateEvaluationSetRequest"];

export type UpdateEvaluationQuestionRequest =
  Schemas["UpdateEvaluationQuestionRequest"];

export type ImportCasesRequest = Schemas["ImportCasesRequest"];

export type ImportCasesResponse = Served<Schemas["ImportCasesResponse"]>;

export type PublishDatasetResponse = Served<Schemas["PublishDatasetResponse"]>;

export type DuplicateDatasetResponse = Served<
  Schemas["DuplicateDatasetResponse"]
>;

export type DatasetValidationIssue = Served<Schemas["DatasetValidationIssue"]>;

export type ValidateDatasetResponse = Served<
  Schemas["ValidateDatasetResponse"]
>;

export type EvaluationDatasetVersionResponse = Served<
  Schemas["EvaluationDatasetVersionResponse"]
>;

export type EvaluationDatasetVersionListResponse = Served<
  Schemas["EvaluationDatasetVersionListResponse"]
>;

export type ConvertFeedbackToCasesRequest =
  Schemas["ConvertFeedbackToCasesRequest"];

export type ConvertFeedbackToCasesResponse = Served<
  Schemas["ConvertFeedbackToCasesResponse"]
>;

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

export type LocalModelMetrics = Served<Schemas["LocalModelMetrics"]>;

export type EvaluationRunSummaryResponse = Served<
  Schemas["EvaluationRunSummaryResponse"]
>;

export type EvaluationRunListResponse = Served<
  Schemas["EvaluationRunListResponse"]
>;

export type MetricDelta = Served<Schemas["MetricDelta"]>;

export type CaseComparisonRow = Served<Schemas["CaseComparisonRow"]>;

export type RunComparisonResponse = Served<Schemas["RunComparisonResponse"]>;

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

// ---------------------------------------------------------------------------
// F226 — Benchmark suites and model-profile comparison
// ---------------------------------------------------------------------------

export type BenchmarkSuite = Served<Schemas["BenchmarkSuiteResponse"]>;

export type BenchmarkSuiteListResponse = Served<
  Schemas["BenchmarkSuiteListResponse"]
>;

export type TriggerBenchmarkRunRequest = WithOptional<
  Schemas["TriggerBenchmarkRunRequest"],
  "top_k" | "rerank"
>;

export type TriggerBenchmarkRunResponse = Served<
  Schemas["TriggerBenchmarkRunResponse"]
>;

export type ProviderProfileSummary = Served<Schemas["ProviderProfileSummary"]>;

export type ReleaseGateRecommendation = Served<
  Schemas["ReleaseGateRecommendation"]
>;

export type ModelProfileComparisonReport = Served<
  Schemas["ModelProfileComparisonReport"]
>;

export async function listBenchmarkSuites(): Promise<BenchmarkSuiteListResponse> {
  return apiRequest<BenchmarkSuiteListResponse>(
    "/evaluations/benchmark-suites",
  );
}

export async function triggerBenchmarkRun(
  suiteId: string,
  payload: TriggerBenchmarkRunRequest,
): Promise<TriggerBenchmarkRunResponse> {
  return apiRequest<TriggerBenchmarkRunResponse>(
    `/evaluations/benchmark-suites/${encodeURIComponent(suiteId)}/run`,
    { method: "POST", json: payload },
  );
}

export async function getModelProfileComparisonReport(
  evaluationSetId?: string | null,
): Promise<ModelProfileComparisonReport> {
  return apiRequest<ModelProfileComparisonReport>(
    "/evaluations/model-profile-report",
    {
      query: evaluationSetId
        ? { evaluation_set_id: evaluationSetId }
        : undefined,
    },
  );
}

// ---------------------------------------------------------------------------
// F234 — Multilingual evaluation datasets and regression gates
// ---------------------------------------------------------------------------

export type LanguageBreakdownItem = Served<Schemas["LanguageBreakdownItem"]>;

export type LanguageBreakdownResponse = Served<
  Schemas["LanguageBreakdownResponse"]
>;

export type LanguageCoverageItem = Served<Schemas["LanguageCoverageItem"]>;

export type LanguageCoverageResponse = Served<
  Schemas["LanguageCoverageResponse"]
>;

export const EVAL_LANGUAGE_OPTIONS: {
  value: EvalLanguageCode;
  label: string;
}[] = [
  { value: "en", label: "English" },
  { value: "de", label: "German" },
  { value: "es", label: "Spanish" },
  { value: "fr", label: "French" },
];

export async function getLanguageBreakdown(
  evaluationRunId: string,
): Promise<LanguageBreakdownResponse> {
  return apiRequest<LanguageBreakdownResponse>(
    `/evaluations/runs/${encodeURIComponent(evaluationRunId)}/language-breakdown`,
  );
}

export async function getLanguageCoverage(
  evaluationSetId: string,
): Promise<LanguageCoverageResponse> {
  return apiRequest<LanguageCoverageResponse>(
    `/evaluation-sets/${encodeURIComponent(evaluationSetId)}/language-coverage`,
  );
}
