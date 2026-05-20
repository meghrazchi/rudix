import { apiRequest, type ApiRequestOptions } from "@/lib/api/request";

export type PipelineNodeStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "skipped";

export type PipelineNode = {
  id: string;
  label: string;
  section: "ingestion" | "query" | "evaluation";
  description?: string;
  status: PipelineNodeStatus;
  started_at?: string | null;
  completed_at?: string | null;
  duration_ms?: number | null;
  metrics?: Record<string, unknown>;
};

export type PipelineEdge = {
  id: string;
  source: string;
  target: string;
};

export type PipelineRunGraphResponse = {
  pipeline_run_id: string;
  pipeline_type: string;
  status: string;
  nodes: PipelineNode[];
  edges: PipelineEdge[];
};

export type PipelineRunResolveResponse = {
  pipeline_run_id: string;
  pipeline_type: string;
  status: string;
};

export type PipelineNodeDetailResponse = {
  node_id: string;
  title: string;
  description: string;
  status: PipelineNodeStatus;
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
  config: Record<string, unknown>;
  logs: string[];
  error_message: string | null;
  error_details: Record<string, unknown>;
  metrics: Record<string, unknown>;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
};

export type PipelineStepListResponse = {
  steps: string[];
};

export type PipelineRequestOptions = Pick<
  ApiRequestOptions,
  "apiBaseUrl" | "token" | "organizationId" | "signal"
>;

export async function fetchPipelineSteps(
  options: PipelineRequestOptions = {},
): Promise<PipelineStepListResponse> {
  return apiRequest<PipelineStepListResponse>("/pipeline/steps", {
    ...options,
    retry: { maxRetries: 1 },
  });
}

export async function fetchPipelineRunGraph(
  runId: string,
  options: PipelineRequestOptions = {},
): Promise<PipelineRunGraphResponse> {
  return apiRequest<PipelineRunGraphResponse>(
    `/pipeline/runs/${encodeURIComponent(runId)}`,
    options,
  );
}

export async function resolvePipelineRun(
  params: {
    run_type?: string | null;
    document_id?: string | null;
    chat_message_id?: string | null;
    evaluation_run_id?: string | null;
  },
  options: PipelineRequestOptions = {},
): Promise<PipelineRunResolveResponse> {
  return apiRequest<PipelineRunResolveResponse>("/pipeline/runs/resolve", {
    ...options,
    query: {
      run_type: params.run_type ?? undefined,
      document_id: params.document_id ?? undefined,
      chat_message_id: params.chat_message_id ?? undefined,
      evaluation_run_id: params.evaluation_run_id ?? undefined,
    },
  });
}

export async function fetchPipelineNodeDetail(
  runId: string,
  nodeId: string,
  options: PipelineRequestOptions = {},
): Promise<PipelineNodeDetailResponse> {
  return apiRequest<PipelineNodeDetailResponse>(
    `/pipeline/runs/${encodeURIComponent(runId)}/nodes/${encodeURIComponent(nodeId)}`,
    options,
  );
}
