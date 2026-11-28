import type { Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

export type ToolPolicyOverrideState = Served<
  Schemas["ToolPolicyOverrideState"]
>;

export type OrgToolPolicyOverride = Served<Schemas["OrgToolPolicyOverride"]>;

export type OrgBudgetPolicySummary = Served<Schemas["OrgBudgetPolicySummary"]>;

export type AgentPolicyResponse = Served<Schemas["AgentPolicyResponse"]>;

export type ToolPolicyUpsertRequest = Schemas["ToolPolicyUpsertRequest"];

export type ToolPolicyUpsertResponse = Served<
  Schemas["ToolPolicyUpsertResponse"]
>;

export type EffectivePolicyResponse = Served<
  Schemas["EffectivePolicyResponse"]
>;

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
