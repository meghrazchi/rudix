import type { Served, WithOptional } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

const BASE = "/admin/portability";

export type WorkspaceExportSection =
  | "collections"
  | "document_metadata"
  | "chat_transcripts"
  | "evaluation_datasets"
  | "evaluation_results"
  | "audit_logs"
  | "settings"
  | "api_metadata"
  | "webhook_metadata";

export type WorkspacePortabilityStatus =
  | "queued"
  | "running"
  | "validated"
  | "completed"
  | "failed"
  | "validation_failed"
  | "expired";

export type WorkspacePortabilityJob = Served<
  Schemas["WorkspacePortabilityJobResponse"]
>;

export type WorkspacePortabilityJobList = Served<
  Schemas["WorkspacePortabilityJobListResponse"]
>;

export type CreateWorkspaceExportRequest = WithOptional<
  Schemas["WorkspaceExportRequest"],
  "max_rows_per_section"
>;

export type CreateWorkspaceImportRequest = Schemas["WorkspaceImportRequest"];

export const WORKSPACE_EXPORT_SECTION_LABELS: Record<
  WorkspaceExportSection,
  string
> = {
  collections: "Collections",
  document_metadata: "Document metadata",
  chat_transcripts: "Chat transcripts",
  evaluation_datasets: "Evaluation datasets",
  evaluation_results: "Evaluation results",
  audit_logs: "Audit logs",
  settings: "Settings",
  api_metadata: "API metadata",
  webhook_metadata: "Webhook metadata",
};

export const DEFAULT_WORKSPACE_EXPORT_SECTIONS: WorkspaceExportSection[] = [
  "collections",
  "document_metadata",
  "chat_transcripts",
  "evaluation_datasets",
  "evaluation_results",
  "audit_logs",
  "settings",
  "api_metadata",
  "webhook_metadata",
];

export async function listWorkspacePortabilityJobs(query?: {
  limit?: number;
  offset?: number;
}): Promise<WorkspacePortabilityJobList> {
  return apiRequest<WorkspacePortabilityJobList>(`${BASE}/jobs`, {
    query,
  });
}

export async function createWorkspaceExport(
  payload: CreateWorkspaceExportRequest,
): Promise<WorkspacePortabilityJob> {
  return apiRequest<WorkspacePortabilityJob>(`${BASE}/exports`, {
    method: "POST",
    json: payload,
    authRetry: "never",
  });
}

export async function createWorkspaceImport(
  payload: CreateWorkspaceImportRequest,
): Promise<WorkspacePortabilityJob> {
  return apiRequest<WorkspacePortabilityJob>(`${BASE}/imports`, {
    method: "POST",
    json: payload,
    authRetry: "never",
  });
}

export async function downloadWorkspacePortabilityArtifact(
  jobId: string,
): Promise<Blob> {
  return apiRequest<Blob>(
    `${BASE}/jobs/${encodeURIComponent(jobId)}/download`,
    {
      responseType: "blob",
    },
  );
}
