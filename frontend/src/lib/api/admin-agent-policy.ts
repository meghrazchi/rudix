import { apiRequest } from "@/lib/api/request";

export type ToolPolicyOverrideState = {
  tool_name: string;
  enabled: boolean;
  approval_required: boolean;
  required_roles: string[];
  max_calls_per_run: number;
  max_input_bytes: number;
  max_output_bytes: number;
  timeout_ms: number;
  max_retry_attempts: number;
  is_overridden: boolean;
};

export type OrgToolPolicyOverride = {
  tool_name: string;
  enabled: boolean;
  approval_required?: boolean | null;
  required_roles?: string[] | null;
  max_calls_per_run?: number | null;
  max_input_bytes?: number | null;
  max_output_bytes?: number | null;
  timeout_ms?: number | null;
  max_retry_attempts?: number | null;
  updated_at?: string | null;
  updated_by_user_id?: string | null;
};

export type OrgBudgetPolicySummary = {
  max_steps?: number | null;
  max_tool_calls_per_run?: number | null;
  max_tool_timeout_ms?: number | null;
  max_tool_input_bytes?: number | null;
  max_tool_output_bytes?: number | null;
  max_tool_retry_attempts?: number | null;
  max_total_tokens?: number | null;
  max_total_cost_usd?: number | null;
};

export type AgentPolicyResponse = {
  organization_id: string;
  org_budget: OrgBudgetPolicySummary;
  tool_overrides: OrgToolPolicyOverride[];
  resolved_tools: ToolPolicyOverrideState[];
  policy_updated_at?: string | null;
};

export type ToolPolicyUpsertRequest = {
  enabled?: boolean;
  approval_required?: boolean | null;
  required_roles?: string[] | null;
  max_calls_per_run?: number | null;
  max_input_bytes?: number | null;
  max_output_bytes?: number | null;
  timeout_ms?: number | null;
  max_retry_attempts?: number | null;
};

export type ToolPolicyUpsertResponse = {
  organization_id: string;
  override: OrgToolPolicyOverride;
  audit_recorded: boolean;
};

export type EffectivePolicyResponse = {
  run_id: string;
  organization_id: string;
  snapshot?: Record<string, unknown> | null;
  resolved_tools: ToolPolicyOverrideState[];
  org_budget?: OrgBudgetPolicySummary | null;
  snapshot_recorded_at?: string | null;
};

export async function getAgentPolicy(): Promise<AgentPolicyResponse> {
  return apiRequest<AgentPolicyResponse>("/admin/agent-policy");
}

export async function upsertToolPolicy(
  toolName: string,
  payload: ToolPolicyUpsertRequest,
): Promise<ToolPolicyUpsertResponse> {
  return apiRequest<ToolPolicyUpsertResponse>(
    `/admin/agent-policy/tools/${encodeURIComponent(toolName)}`,
    { method: "PUT", json: payload },
  );
}

export async function deleteToolPolicy(toolName: string): Promise<void> {
  await apiRequest<void>(
    `/admin/agent-policy/tools/${encodeURIComponent(toolName)}`,
    { method: "DELETE" },
  );
}

export async function getEffectivePolicyForRun(
  runId: string,
): Promise<EffectivePolicyResponse> {
  return apiRequest<EffectivePolicyResponse>(
    `/admin/agent-policy/runs/${encodeURIComponent(runId)}/effective-policy`,
  );
}
