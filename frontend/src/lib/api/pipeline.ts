import type { Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest, type ApiRequestOptions } from "@/lib/api/request";

type Schemas = components["schemas"];

export type PipelineNode = Served<Schemas["PipelineNodeResponse"]>;

export type PipelineNodeStatus = PipelineNode["status"];

export type PipelineEdge = Schemas["PipelineEdgeResponse"];

export type PipelineRunGraphResponse = Served<
  Schemas["PipelineRunGraphResponse"]
>;

export type PipelineRunResolveResponse = Served<
  Schemas["PipelineRunResolveResponse"]
>;

export type PipelineNodeDetailResponse = Served<
  Schemas["PipelineNodeDetailResponse"]
>;

export type PipelineStepListResponse = Served<
  Schemas["PipelineStepListResponse"]
>;

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
