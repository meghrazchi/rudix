import type { Overlay, Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

// ---------------------------------------------------------------------------
// Workflow types
// ---------------------------------------------------------------------------

export type WorkflowType =
  | "audit_evidence_pack"
  | "policy_comparison"
  | "contract_review"
  | "onboarding_faq"
  | "custom";

export type WorkflowStatus = "active" | "archived";

export type ScopeMode = "all" | "collection" | "docs" | "none";

export type WorkflowStep = Served<Schemas["WorkflowStepResponse"]>;

export type WorkflowResponse = Overlay<
  Served<Schemas["WorkflowResponse"]>,
  { workflow_type: WorkflowType; status: WorkflowStatus }
>;

export type WorkflowListResponse = Overlay<
  Served<Schemas["WorkflowListResponse"]>,
  { items: WorkflowResponse[] }
>;

export type CreateWorkflowRequest = Schemas["CreateWorkflowRequest"];

export type UpdateWorkflowRequest = Schemas["UpdateWorkflowRequest"];

// ---------------------------------------------------------------------------
// Preference types
// ---------------------------------------------------------------------------

export type MemoryPreferenceResponse = Served<
  Schemas["MemoryPreferenceResponse"]
>;

export type UpsertMemoryPreferenceRequest =
  Schemas["UpsertMemoryPreferenceRequest"];

// ---------------------------------------------------------------------------
// Workflow API
// ---------------------------------------------------------------------------

export async function listWorkflows(params?: {
  workflow_type?: WorkflowType;
  query?: string;
  limit?: number;
  offset?: number;
}): Promise<WorkflowListResponse> {
  const search = new URLSearchParams();
  if (params?.workflow_type) search.set("workflow_type", params.workflow_type);
  if (params?.query) search.set("query", params.query);
  if (params?.limit != null) search.set("limit", String(params.limit));
  if (params?.offset != null) search.set("offset", String(params.offset));
  const qs = search.toString();
  return apiRequest<WorkflowListResponse>(
    `/memory/workflows${qs ? `?${qs}` : ""}`,
  );
}

export async function getWorkflow(
  workflowId: string,
): Promise<WorkflowResponse> {
  return apiRequest<WorkflowResponse>(`/memory/workflows/${workflowId}`);
}

export async function createWorkflow(
  payload: CreateWorkflowRequest,
): Promise<WorkflowResponse> {
  return apiRequest<WorkflowResponse>("/memory/workflows", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateWorkflow(
  workflowId: string,
  payload: UpdateWorkflowRequest,
): Promise<WorkflowResponse> {
  return apiRequest<WorkflowResponse>(`/memory/workflows/${workflowId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function incrementWorkflowUse(workflowId: string): Promise<void> {
  await apiRequest<void>(`/memory/workflows/${workflowId}/increment-use`, {
    method: "POST",
  });
}

// ---------------------------------------------------------------------------
// Admin workflow API
// ---------------------------------------------------------------------------

export async function adminListWorkflows(params?: {
  status?: WorkflowStatus;
  workflow_type?: WorkflowType;
  query?: string;
  limit?: number;
  offset?: number;
}): Promise<WorkflowListResponse> {
  const search = new URLSearchParams();
  if (params?.status) search.set("status", params.status);
  if (params?.workflow_type) search.set("workflow_type", params.workflow_type);
  if (params?.query) search.set("query", params.query);
  if (params?.limit != null) search.set("limit", String(params.limit));
  if (params?.offset != null) search.set("offset", String(params.offset));
  const qs = search.toString();
  return apiRequest<WorkflowListResponse>(
    `/admin/memory/workflows${qs ? `?${qs}` : ""}`,
  );
}

export async function adminArchiveWorkflow(
  workflowId: string,
): Promise<WorkflowResponse> {
  return apiRequest<WorkflowResponse>(
    `/admin/memory/workflows/${workflowId}/archive`,
    {
      method: "POST",
    },
  );
}

export async function adminDeleteWorkflow(workflowId: string): Promise<void> {
  await apiRequest<void>(`/admin/memory/workflows/${workflowId}`, {
    method: "DELETE",
  });
}

// ---------------------------------------------------------------------------
// User preferences API
// ---------------------------------------------------------------------------

export async function getMemoryPreferences(): Promise<MemoryPreferenceResponse> {
  return apiRequest<MemoryPreferenceResponse>("/memory/preferences");
}

export async function upsertMemoryPreferences(
  payload: UpsertMemoryPreferenceRequest,
): Promise<MemoryPreferenceResponse> {
  return apiRequest<MemoryPreferenceResponse>("/memory/preferences", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function deleteMemoryPreferences(): Promise<void> {
  await apiRequest<void>("/memory/preferences", { method: "DELETE" });
}
