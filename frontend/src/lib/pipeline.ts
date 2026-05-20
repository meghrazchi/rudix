import {
  fetchPipelineNodeDetail as fetchPipelineNodeDetailRequest,
  resolvePipelineRun as resolvePipelineRunRequest,
  fetchPipelineRunGraph as fetchPipelineRunGraphRequest,
  type PipelineEdge,
  type PipelineNode,
  type PipelineNodeDetailResponse,
  type PipelineNodeStatus,
  type PipelineRunResolveResponse,
  type PipelineRunGraphResponse,
} from "@/lib/api/pipeline";

export type {
  PipelineEdge,
  PipelineNode,
  PipelineNodeDetailResponse,
  PipelineNodeStatus,
  PipelineRunResolveResponse,
  PipelineRunGraphResponse,
};

export type PipelineApiOptions = {
  apiBaseUrl?: string;
  token?: string;
  organizationId?: string;
};

export async function fetchPipelineRunGraph(
  runId: string,
  options: PipelineApiOptions = {},
): Promise<PipelineRunGraphResponse> {
  return fetchPipelineRunGraphRequest(runId, options);
}

export async function fetchPipelineNodeDetail(
  runId: string,
  nodeId: string,
  options: PipelineApiOptions = {},
): Promise<PipelineNodeDetailResponse> {
  return fetchPipelineNodeDetailRequest(runId, nodeId, options);
}

export async function resolvePipelineRun(
  params: {
    run_type?: string | null;
    document_id?: string | null;
    chat_message_id?: string | null;
    evaluation_run_id?: string | null;
  },
  options: PipelineApiOptions = {},
): Promise<PipelineRunResolveResponse> {
  return resolvePipelineRunRequest(params, options);
}

export const fallbackPipelineGraph: PipelineRunGraphResponse = {
  pipeline_run_id: "sample-run",
  pipeline_type: "document.process",
  status: "running",
  nodes: [
    {
      id: "upload",
      label: "Upload",
      section: "ingestion",
      status: "completed",
      duration_ms: 1240,
      metrics: { throughput: "3.4 MB/s" },
    },
    {
      id: "extract",
      label: "Extract",
      section: "ingestion",
      status: "completed",
      duration_ms: 2100,
      metrics: { page_count: 12 },
    },
    {
      id: "chunk",
      label: "Chunk",
      section: "ingestion",
      status: "running",
      metrics: { chunk_size_tokens: 700, chunk_overlap_tokens: 120 },
    },
    {
      id: "embed",
      label: "Embed",
      section: "ingestion",
      status: "pending",
    },
    {
      id: "index",
      label: "Upsert",
      section: "ingestion",
      status: "pending",
    },
    {
      id: "retrieve",
      label: "Retrieve",
      section: "query",
      status: "pending",
    },
    {
      id: "rerank",
      label: "Rerank",
      section: "query",
      status: "pending",
    },
    {
      id: "llm",
      label: "LLM",
      section: "query",
      status: "pending",
    },
  ],
  edges: [
    { id: "e-upload-extract", source: "upload", target: "extract" },
    { id: "e-extract-chunk", source: "extract", target: "chunk" },
    { id: "e-chunk-embed", source: "chunk", target: "embed" },
    { id: "e-embed-index", source: "embed", target: "index" },
    { id: "e-retrieve-rerank", source: "retrieve", target: "rerank" },
    { id: "e-rerank-llm", source: "rerank", target: "llm" },
  ],
};

export const fallbackChatPipelineGraph: PipelineRunGraphResponse = {
  pipeline_run_id: "sample-chat-run",
  pipeline_type: "chat.answer",
  status: "completed",
  nodes: [
    {
      id: "embed-query",
      label: "Embed query",
      section: "query",
      status: "completed",
      duration_ms: 42,
      metrics: { embedding_model: "text-embedding-3-small" },
    },
    {
      id: "retrieve",
      label: "Retrieve",
      section: "query",
      status: "completed",
      duration_ms: 97,
      metrics: { retrieval_count: 18 },
    },
    {
      id: "rerank",
      label: "Rerank",
      section: "query",
      status: "completed",
      duration_ms: 58,
      metrics: { selected_count: 6 },
    },
    {
      id: "build-prompt",
      label: "Build prompt",
      section: "query",
      status: "completed",
      duration_ms: 34,
    },
    {
      id: "llm",
      label: "LLM",
      section: "query",
      status: "completed",
      duration_ms: 312,
    },
    {
      id: "validate-citations",
      label: "Validate citations",
      section: "query",
      status: "completed",
      duration_ms: 73,
    },
    {
      id: "persist-response",
      label: "Persist response",
      section: "query",
      status: "completed",
      duration_ms: 28,
    },
  ],
  edges: [
    { id: "e-chat-embed-retrieve", source: "embed-query", target: "retrieve" },
    { id: "e-chat-retrieve-rerank", source: "retrieve", target: "rerank" },
    { id: "e-chat-rerank-build", source: "rerank", target: "build-prompt" },
    { id: "e-chat-build-llm", source: "build-prompt", target: "llm" },
    { id: "e-chat-llm-validate", source: "llm", target: "validate-citations" },
    { id: "e-chat-validate-persist", source: "validate-citations", target: "persist-response" },
  ],
};

export const fallbackEvaluationPipelineGraph: PipelineRunGraphResponse = {
  pipeline_run_id: "sample-eval-run",
  pipeline_type: "evaluation.run",
  status: "running",
  nodes: [
    {
      id: "load-set",
      label: "Load set",
      section: "evaluation",
      status: "completed",
      duration_ms: 65,
    },
    {
      id: "run-question",
      label: "Run question",
      section: "evaluation",
      status: "running",
      duration_ms: 830,
      metrics: { processed_questions: 12, total_questions: 40 },
    },
    {
      id: "score-metrics",
      label: "Score metrics",
      section: "evaluation",
      status: "pending",
    },
    {
      id: "aggregate-summary",
      label: "Aggregate summary",
      section: "evaluation",
      status: "pending",
    },
    {
      id: "persist-results",
      label: "Persist results",
      section: "evaluation",
      status: "pending",
    },
  ],
  edges: [
    { id: "e-eval-load-run", source: "load-set", target: "run-question" },
    { id: "e-eval-run-score", source: "run-question", target: "score-metrics" },
    { id: "e-eval-score-aggregate", source: "score-metrics", target: "aggregate-summary" },
    { id: "e-eval-aggregate-persist", source: "aggregate-summary", target: "persist-results" },
  ],
};

export const fallbackNodeDetail: PipelineNodeDetailResponse = {
  node_id: "upload",
  title: "Upload",
  description: "Initial file ingestion from private object storage.",
  status: "completed",
  inputs: {
    filename: "invoice_q4_final.pdf",
    size_bytes: 350208,
    file_type: "pdf",
  },
  outputs: {
    bucket: "documents",
    object_key: "uploads/org/user/doc.pdf",
    checksum: "sha256:4c8f...",
  },
  config: {
    provider: "minio",
    max_upload_size_mb: 25,
  },
  logs: ["Connection established", "Checksum verified", "Transfer completed"],
  error_message: null,
  error_details: {},
  metrics: {
    duration_ms: 1240,
    throughput: "3.4 MB/s",
  },
  started_at: null,
  completed_at: null,
  duration_ms: 1240,
};
