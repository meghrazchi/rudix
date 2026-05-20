import { apiRequest } from "@/lib/api/request";

export type AgentRuntimeMode = "auto" | "answer" | "summarize" | "compare";

export type AgentBudgetConfig = {
  max_steps?: number;
  max_runtime_ms?: number;
  max_tool_calls?: number;
  max_total_tokens?: number | null;
  max_total_cost_usd?: number | null;
};

export type AgentRuntimeRequest = {
  objective: string;
  mode?: AgentRuntimeMode;
  question?: string | null;
  document_query?: string | null;
  document_ids?: string[];
  top_k?: number;
  rerank?: boolean;
  approval_ids?: Record<string, string>;
  budget?: AgentBudgetConfig | null;
  metadata?: Record<string, unknown>;
};

export type AgentRuntimeError = {
  code: string;
  message: string;
  retryable: boolean;
  request_id?: string | null;
  details: Record<string, unknown>;
};

export type AgentRuntimeOutcome = {
  answer: string;
  citations: Array<Record<string, unknown>>;
  confidence: Record<string, unknown>;
  not_found: boolean;
  mode: AgentRuntimeMode;
};

export type AgentRuntimeResult = {
  run_id: string;
  status: string;
  steps_executed: number;
  tool_calls_executed: number;
  total_tokens: number;
  total_cost_usd: number;
  outcome?: AgentRuntimeOutcome | null;
  error?: AgentRuntimeError | null;
};

export type AgentRunCreateRequest = {
  agentic_mode: boolean;
  request: AgentRuntimeRequest;
};

export type AgentRunCreateResponse = {
  run: AgentRuntimeResult;
};

export type AgentStepResponse = {
  step_id: string;
  sequence: number;
  step_name: string;
  status: string;
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
  metrics: Record<string, unknown>;
  observation: Record<string, unknown>;
  error_message: string | null;
  error_details: Record<string, unknown>;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  created_at: string;
  updated_at: string;
};

export type AgentToolCallResponse = {
  tool_call_id: string;
  agent_step_id: string | null;
  call_id: string;
  tool_name: string;
  surface: string;
  effect_policy: string;
  status: string;
  attempt_number: number;
  arguments: Record<string, unknown>;
  output: Record<string, unknown>;
  error: Record<string, unknown>;
  input_size_bytes: number | null;
  output_size_bytes: number | null;
  latency_ms: number | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type AgentApprovalResponse = {
  approval_id: string;
  agent_step_id: string | null;
  tool_call_id: string | null;
  requested_by_user_id: string | null;
  decided_by_user_id: string | null;
  status: string;
  request_summary: string | null;
  decision_reason: string | null;
  request_payload: Record<string, unknown>;
  decision_payload: Record<string, unknown>;
  expires_at: string | null;
  decided_at: string | null;
  created_at: string;
  updated_at: string;
};

export type AgentApprovalDecisionRequest = {
  status: "approved" | "rejected";
  reason?: string | null;
  decision_payload?: Record<string, unknown>;
};

export type AgentRunDetailResponse = {
  run_id: string;
  organization_id: string;
  user_id: string | null;
  status: string;
  surface: string;
  objective: string | null;
  max_steps: number | null;
  max_parallel_tool_calls: number | null;
  budget: Record<string, unknown>;
  costs: Record<string, unknown>;
  outcome: Record<string, unknown>;
  observations: Record<string, unknown>;
  total_cost_usd: number | null;
  trace_request_id: string | null;
  error_message: string | null;
  error_details: Record<string, unknown>;
  started_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
  created_at: string;
  updated_at: string;
  steps: AgentStepResponse[];
  tool_calls: AgentToolCallResponse[];
  approvals: AgentApprovalResponse[];
};

export async function createAgentRun(
  payload: AgentRunCreateRequest,
): Promise<AgentRunCreateResponse> {
  return apiRequest<AgentRunCreateResponse>("/agent/runs", {
    method: "POST",
    json: payload,
    authRetry: "safe",
  });
}

export async function getAgentRun(runId: string): Promise<AgentRunDetailResponse> {
  return apiRequest<AgentRunDetailResponse>(`/agent/runs/${encodeURIComponent(runId)}`);
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
