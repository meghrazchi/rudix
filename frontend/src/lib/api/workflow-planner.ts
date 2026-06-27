import { apiRequest } from "@/lib/api/request";
import type { AgentRuntimeMode, AgentRuntimeRequest } from "@/lib/api/agent";

export type WorkflowType =
  | "audit_evidence_pack"
  | "policy_comparison"
  | "contract_obligation_analysis"
  | "onboarding_faq_preparation"
  | "connector_content_summarization"
  | "low_confidence_answer_investigation";

export type WorkflowAction =
  | "export"
  | "share"
  | "connector_sync"
  | "public_link"
  | "permission_change";

export type WorkflowPlanStep = {
  step_name: string;
  tool_name: string;
  rationale: string | null;
  arguments: Record<string, unknown>;
};

export type WorkflowPlanPreviewRequest = {
  workflow_type: WorkflowType;
  request?: AgentRuntimeRequest | null;
  requested_actions?: WorkflowAction[];
};

export type WorkflowPlanPreviewResponse = {
  objective: string;
  mode: AgentRuntimeMode;
  plan: WorkflowPlanStep[];
  workflow_type: WorkflowType | null;
  planner_strategy: string;
  planner_high_risk: boolean;
  requires_approval: boolean;
  requested_actions: WorkflowAction[];
  request: AgentRuntimeRequest;
};

export async function previewWorkflowPlan(
  payload: WorkflowPlanPreviewRequest,
): Promise<WorkflowPlanPreviewResponse> {
  return apiRequest<WorkflowPlanPreviewResponse>("/agent/workflows/preview", {
    method: "POST",
    json: payload,
    authRetry: "safe",
  });
}
