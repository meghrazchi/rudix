import { apiRequest } from "@/lib/api/request";

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

export type WorkflowStep = {
  label: string;
  query_template: string | null;
  scope: ScopeMode;
  collection_ids: string[];
};

export type WorkflowResponse = {
  workflow_id: string;
  organization_id: string;
  created_by_id: string | null;
  name: string;
  description: string | null;
  workflow_type: WorkflowType;
  status: WorkflowStatus;
  steps: WorkflowStep[];
  role_scope: string[] | null;
  collection_scope_ids: string[] | null;
  verified_knowledge_card_id: string | null;
  use_count: number;
  created_at: string;
  updated_at: string;
};

export type WorkflowListResponse = {
  items: WorkflowResponse[];
  total: number;
  limit: number;
  offset: number;
};

export type CreateWorkflowRequest = {
  name: string;
  description?: string | null;
  workflow_type?: WorkflowType;
  steps?: WorkflowStep[];
  role_scope?: string[] | null;
  collection_scope_ids?: string[] | null;
  verified_knowledge_card_id?: string | null;
};

export type UpdateWorkflowRequest = Partial<CreateWorkflowRequest>;

// ---------------------------------------------------------------------------
// Preference types
// ---------------------------------------------------------------------------

export type MemoryPreferenceResponse = {
  preference_id: string;
  organization_id: string;
  user_id: string;
  preferred_scope: ScopeMode | null;
  preferred_collection_ids: string[] | null;
  rag_profile_id: string | null;
  answer_language: string | null;
  extra_defaults: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type UpsertMemoryPreferenceRequest = {
  preferred_scope?: ScopeMode | null;
  preferred_collection_ids?: string[] | null;
  rag_profile_id?: string | null;
  answer_language?: string | null;
  extra_defaults?: Record<string, unknown> | null;
};

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
