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

type PipelineApiOptions = {
  apiBaseUrl?: string;
  token?: string;
  organizationId?: string;
};

const DEFAULT_API_BASE = "http://localhost:8000/api/v1";

export class PipelineApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "PipelineApiError";
    this.status = status;
  }
}

function resolveApiBaseUrl(apiBaseUrl?: string): string {
  const resolved = apiBaseUrl ?? process.env.NEXT_PUBLIC_API_URL ?? DEFAULT_API_BASE;
  return resolved.replace(/\/$/, "");
}

function buildHeaders(options: PipelineApiOptions): HeadersInit {
  const headers: Record<string, string> = {};
  if (options.token?.trim()) {
    headers.Authorization = `Bearer ${options.token.trim()}`;
  }
  if (options.organizationId?.trim()) {
    headers["X-Organization-ID"] = options.organizationId.trim();
  }
  return headers;
}

async function fetchJson<T>(url: string, options: PipelineApiOptions): Promise<T> {
  const response = await fetch(url, {
    method: "GET",
    headers: buildHeaders(options),
    cache: "no-store",
  });

  const rawBody = await response.text();

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    if (rawBody) {
      try {
        const parsed = JSON.parse(rawBody) as { detail?: string; message?: string };
        if (typeof parsed.detail === "string" && parsed.detail.trim()) {
          message = parsed.detail;
        } else if (typeof parsed.message === "string" && parsed.message.trim()) {
          message = parsed.message;
        }
      } catch {
        message = rawBody;
      }
    }
    throw new PipelineApiError(response.status, message);
  }

  if (!rawBody) {
    return {} as T;
  }

  return JSON.parse(rawBody) as T;
}

export async function fetchPipelineRunGraph(
  runId: string,
  options: PipelineApiOptions = {},
): Promise<PipelineRunGraphResponse> {
  const base = resolveApiBaseUrl(options.apiBaseUrl);
  return fetchJson<PipelineRunGraphResponse>(`${base}/pipeline/runs/${runId}`, options);
}

export async function fetchPipelineNodeDetail(
  runId: string,
  nodeId: string,
  options: PipelineApiOptions = {},
): Promise<PipelineNodeDetailResponse> {
  const base = resolveApiBaseUrl(options.apiBaseUrl);
  return fetchJson<PipelineNodeDetailResponse>(`${base}/pipeline/runs/${runId}/nodes/${nodeId}`, options);
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
  logs: [
    "Connection established",
    "Checksum verified",
    "Transfer completed",
  ],
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
