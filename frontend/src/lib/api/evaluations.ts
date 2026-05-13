import { apiRequest } from "@/lib/api/request";

export type EvaluationSetResponse = {
  evaluation_set_id: string;
  name: string;
  description: string | null;
  question_count: number;
  created_at: string;
  updated_at: string;
};

export type EvaluationSetListResponse = {
  items: EvaluationSetResponse[];
  total: number;
  limit: number;
  offset: number;
};

export type CreateEvaluationSetRequest = {
  name: string;
  description?: string | null;
};

export type EvaluationQuestionResponse = {
  evaluation_question_id: string;
  evaluation_set_id: string;
  question: string;
  expected_answer: string | null;
  expected_document_id: string | null;
  expected_page_number: number | null;
  tags: string[];
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type EvaluationQuestionListResponse = {
  evaluation_set_id: string;
  items: EvaluationQuestionResponse[];
  total: number;
  limit: number;
  offset: number;
};

export type CreateEvaluationQuestionRequest = {
  question: string;
  expected_answer?: string | null;
  expected_document_id?: string | null;
  expected_page_number?: number | null;
  tags?: string[];
  metadata?: Record<string, unknown>;
};

export type EvaluationRunConfig = {
  top_k?: number;
  rerank?: boolean;
  model_name?: string | null;
  selected_document_ids?: string[];
  metric_options?: Record<string, boolean | number | string>;
};

export type RunEvaluationRequest = {
  evaluation_set_id: string;
  config?: EvaluationRunConfig;
};

export type RunEvaluationResponse = {
  evaluation_run_id: string;
  status: "queued";
};

export type EvaluationRunResultResponse = {
  evaluation_result_id: string;
  evaluation_question_id: string;
  question: string;
  status: string;
  generated_answer: string | null;
  retrieval_score: number | null;
  faithfulness_score: number | null;
  citation_accuracy_score: number | null;
  answer_relevance_score: number | null;
  latency_ms: number | null;
  metrics: Record<string, unknown>;
  failure_reason: string | null;
  failure_type: string | null;
  details: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type EvaluationRunDetailResponse = {
  evaluation_run_id: string;
  evaluation_set_id: string;
  status: "queued" | "running" | "completed" | "failed";
  config: Record<string, unknown>;
  summary: Record<string, unknown> | null;
  failure_reason: string | null;
  failure_type: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
  results: {
    items: EvaluationRunResultResponse[];
    total: number;
    limit: number;
    offset: number;
  };
};

export async function createEvaluationSet(payload: CreateEvaluationSetRequest): Promise<EvaluationSetResponse> {
  return apiRequest<EvaluationSetResponse>("/evaluation-sets", {
    method: "POST",
    json: payload,
  });
}

export async function listEvaluationSets(params: { limit?: number; offset?: number } = {}): Promise<EvaluationSetListResponse> {
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
  return apiRequest<EvaluationQuestionResponse>(`/evaluation-sets/${encodeURIComponent(evaluationSetId)}/questions`, {
    method: "POST",
    json: payload,
  });
}

export async function listEvaluationQuestions(
  evaluationSetId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<EvaluationQuestionListResponse> {
  return apiRequest<EvaluationQuestionListResponse>(`/evaluation-sets/${encodeURIComponent(evaluationSetId)}/questions`, {
    query: {
      limit: params.limit,
      offset: params.offset,
    },
  });
}

export async function runEvaluation(payload: RunEvaluationRequest): Promise<RunEvaluationResponse> {
  return apiRequest<RunEvaluationResponse>("/evaluations/run", {
    method: "POST",
    json: payload,
  });
}

export async function getEvaluationRun(
  evaluationRunId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<EvaluationRunDetailResponse> {
  return apiRequest<EvaluationRunDetailResponse>(`/evaluations/runs/${encodeURIComponent(evaluationRunId)}`, {
    query: {
      limit: params.limit,
      offset: params.offset,
    },
  });
}
