import { apiRequest } from "@/lib/api/request";
import type { ChatSourceScopeRequest } from "@/lib/api/chat";
import type {
  Overlay,
  WithOptional,
  WithRequired,
} from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

type Schemas = components["schemas"];

export type AgentRuntimeMode = Schemas["AgentRuntimeMode"];

export type AgentBudgetConfig = Partial<Schemas["AgentBudgetConfig-Input"]>;

export type AgentRuntimeRequest = WithOptional<
  Omit<Schemas["AgentRuntimeRequest-Input"], "budget" | "source_scope">,
  "mode"
> & {
  source_scope?: ChatSourceScopeRequest | null;
  budget?: AgentBudgetConfig | null;
};

export type AgentRuntimeError = Schemas["AgentRuntimeError"];

export type AgentRuntimeOutcome = Schemas["AgentRuntimeOutcome"];

export type AgentRuntimeResult = Schemas["AgentRuntimeResult"];

export type AgentRunCreateRequest = Overlay<
  Schemas["AgentRunCreateRequest"],
  { request: AgentRuntimeRequest }
>;

export type AgentRunCreateResponse = Schemas["AgentRunCreateResponse"];

export type AgentStepResponse = Schemas["AgentStepResponse"];

export type AgentToolCallResponse = Schemas["AgentToolCallResponse"];

export type AgentApprovalResponse = Schemas["AgentApprovalResponse"];

export type AgentApprovalQueueItem = Schemas["AgentApprovalQueueItem"];

export type AgentApprovalQueueResponse = Schemas["AgentApprovalQueueResponse"];

export type AgentApprovalDecisionRequest =
  Schemas["AgentApprovalDecisionRequest"];

export type AgentRunDetailResponse = WithRequired<
  Schemas["AgentRunDetailResponse"],
  "steps" | "tool_calls" | "approvals"
>;

export type AgentRunListItem = Schemas["AgentRunListItem"];

export type AgentRunListResponse = Schemas["AgentRunListResponse"];

export async function listAgentApprovals(params?: {
  limit?: number;
  offset?: number;
  status?: string;
}): Promise<AgentApprovalQueueResponse> {
  const searchParams = new URLSearchParams();
  if (params?.limit != null) searchParams.set("limit", String(params.limit));
  if (params?.offset != null) searchParams.set("offset", String(params.offset));
  if (params?.status) searchParams.set("status_filter", params.status);
  const qs = searchParams.toString();
  return apiRequest<AgentApprovalQueueResponse>(
    `/agent/approvals${qs ? `?${qs}` : ""}`,
  );
}

export async function listAgentRuns(params?: {
  limit?: number;
  offset?: number;
  status?: string;
}): Promise<AgentRunListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.limit != null) searchParams.set("limit", String(params.limit));
  if (params?.offset != null) searchParams.set("offset", String(params.offset));
  if (params?.status) searchParams.set("status_filter", params.status);
  const qs = searchParams.toString();
  return apiRequest<AgentRunListResponse>(`/agent/runs${qs ? `?${qs}` : ""}`);
}

export async function cancelAgentRun(
  runId: string,
): Promise<AgentRunDetailResponse> {
  return apiRequest<AgentRunDetailResponse>(
    `/agent/runs/${encodeURIComponent(runId)}/cancel`,
    { method: "POST", authRetry: "safe" },
  );
}

export async function createAgentRun(
  payload: AgentRunCreateRequest,
): Promise<AgentRunCreateResponse> {
  return apiRequest<AgentRunCreateResponse>("/agent/runs", {
    method: "POST",
    json: payload,
    authRetry: "safe",
  });
}

export async function getAgentRun(
  runId: string,
): Promise<AgentRunDetailResponse> {
  return apiRequest<AgentRunDetailResponse>(
    `/agent/runs/${encodeURIComponent(runId)}`,
  );
}

export async function decideAgentRunApproval(
  runId: string,
  approvalId: string,
  payload: AgentApprovalDecisionRequest,
): Promise<AgentApprovalResponse> {
  return apiRequest<AgentApprovalResponse>(
    `/agent/runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}/decision`,
    {
      method: "POST",
      json: payload,
      authRetry: "safe",
    },
  );
}

export type AgentApprovalCreateRequest = Schemas["AgentApprovalCreateRequest"];

export async function createAgentRunApproval(
  runId: string,
  payload: AgentApprovalCreateRequest,
): Promise<AgentApprovalResponse> {
  return apiRequest<AgentApprovalResponse>(
    `/agent/runs/${encodeURIComponent(runId)}/approvals`,
    {
      method: "POST",
      json: payload,
      authRetry: "safe",
    },
  );
}

export async function commentAgentRunApproval(
  runId: string,
  approvalId: string,
  comment: string,
): Promise<AgentApprovalResponse> {
  return apiRequest<AgentApprovalResponse>(
    `/agent/runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}/comment`,
    {
      method: "POST",
      json: { comment },
      authRetry: "safe",
    },
  );
}

// ── Trace replay ──────────────────────────────────────────────────────────────

export type AgentTraceEvent = Schemas["AgentTraceEventResponse"];

export type AgentTraceResponse = Schemas["AgentTraceResponse"];

export type AgentTraceExportResponse = {
  run_id: string;
  organization_id: string;
  status: string;
  objective: string | null;
  surface: string;
  started_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
  created_at: string;
  total_cost_usd: string | null;
  error_message: string | null;
  trace_request_id: string | null;
  steps: Array<{
    sequence: number;
    step_name: string;
    status: string;
    duration_ms: number | null;
    error_message: string | null;
    started_at: string | null;
    completed_at: string | null;
  }>;
  tool_calls: Array<{
    tool_name: string;
    surface: string;
    effect_policy: string;
    status: string;
    attempt_number: number;
    input_size_bytes: number | null;
    output_size_bytes: number | null;
    latency_ms: number | null;
    started_at: string | null;
    completed_at: string | null;
  }>;
  approvals: Array<{
    status: string;
    request_summary: string | null;
    decision_reason: string | null;
    expires_at: string | null;
    decided_at: string | null;
  }>;
  export_safe: true;
  exported_at: string;
};

export type AgentTraceShareRequest = Schemas["AgentTraceShareRequest"];

export type AgentTraceShareResponse = Schemas["AgentTraceShareResponse"];

export type AgentTraceRetentionResponse =
  Schemas["AgentTraceRetentionResponse"];

export type AgentTraceRetentionRequest = Schemas["AgentTraceRetentionRequest"];

export async function getAgentRunTrace(
  runId: string,
): Promise<AgentTraceResponse> {
  return apiRequest<AgentTraceResponse>(
    `/agent/runs/${encodeURIComponent(runId)}/trace`,
  );
}

export async function exportAgentRunTrace(
  runId: string,
): Promise<AgentTraceExportResponse> {
  return apiRequest<AgentTraceExportResponse>(
    `/agent/runs/${encodeURIComponent(runId)}/trace/export`,
  );
}

export async function shareAgentRunTrace(
  runId: string,
  payload: AgentTraceShareRequest,
): Promise<AgentTraceShareResponse> {
  return apiRequest<AgentTraceShareResponse>(
    `/agent/runs/${encodeURIComponent(runId)}/trace/share`,
    { method: "POST", json: payload, authRetry: "safe" },
  );
}

export async function getSharedAgentTrace(
  token: string,
): Promise<AgentTraceResponse> {
  return apiRequest<AgentTraceResponse>(
    `/agent/traces/shared/${encodeURIComponent(token)}`,
  );
}

export async function getTraceRetentionPolicy(): Promise<AgentTraceRetentionResponse> {
  return apiRequest<AgentTraceRetentionResponse>(
    "/admin/agent/trace-retention",
  );
}

export async function updateTraceRetentionPolicy(
  payload: AgentTraceRetentionRequest,
): Promise<AgentTraceRetentionResponse> {
  return apiRequest<AgentTraceRetentionResponse>(
    "/admin/agent/trace-retention",
    { method: "PATCH", json: payload, authRetry: "safe" },
  );
}
