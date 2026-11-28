import { apiRequest } from "@/lib/api/request";
import type { AgentRuntimeRequest } from "@/lib/api/agent";
import type { Overlay } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

type Schemas = components["schemas"];

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

export type WorkflowPlanStep = Schemas["PlannedToolSelection"];

export type WorkflowPlanPreviewRequest = Overlay<
  Schemas["WorkflowPlanRequest"],
  { request: AgentRuntimeRequest }
>;

export type WorkflowPlanPreviewResponse = Overlay<
  Schemas["AgentPlanPreviewResponse"],
  { request: AgentRuntimeRequest }
>;

export async function previewWorkflowPlan(
  payload: WorkflowPlanPreviewRequest,
): Promise<WorkflowPlanPreviewResponse> {
  return apiRequest<WorkflowPlanPreviewResponse>("/agent/workflows/preview", {
    method: "POST",
    json: payload,
    authRetry: "safe",
  });
}
