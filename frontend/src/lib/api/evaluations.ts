import { apiRequest } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/schema";
import type { ChunkingProfileConfigInput } from "@/lib/schemas/chunking-profiles";

type Schemas = components["schemas"];

export type EvaluationSetResponse = Schemas["EvaluationSetResponse"];
export type EvaluationSetListResponse = Schemas["EvaluationSetListResponse"];
export type CreateEvaluationSetRequest = Schemas["CreateEvaluationSetRequest"];
export type EvaluationQuestionResponse = Schemas["EvaluationQuestionResponse"];
export type EvaluationQuestionListResponse =
  Schemas["EvaluationQuestionListResponse"];
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
};

export type RunEvaluationRequest = Omit<BaseRunEvaluationRequest, "config"> & {
  config?: EvaluationRunConfig;
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
