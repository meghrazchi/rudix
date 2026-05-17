import {
  fetchPipelineNodeDetail as fetchPipelineNodeDetailRequest,
  fetchPipelineRunGraph as fetchPipelineRunGraphRequest,
  type PipelineEdge,
  type PipelineNode,
  type PipelineNodeDetailResponse,
  type PipelineNodeStatus,
  type PipelineRunGraphResponse,
} from "@/lib/api/pipeline";

export type {
  PipelineEdge,
  PipelineNode,
  PipelineNodeDetailResponse,
  PipelineNodeStatus,
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
