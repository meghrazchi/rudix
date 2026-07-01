import { apiRequest } from "@/lib/api/request";

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

export type WorkspacePortabilityJob = {
  job_id: string;
  organization_id: string;
  created_by_user_id: string | null;
  job_type: "export" | "import";
  status: WorkspacePortabilityStatus;
  requested_sections: string[];
  parameters: Record<string, unknown>;
  artifact_filename: string | null;
  artifact_mime_type: string | null;
  artifact_size_bytes: number | null;
  validation_errors: Array<{
    section: string;
    path: string;
    code: string;
    message: string;
  }>;
  warnings: Array<{
    section: string;
    code: string;
    message: string;
  }>;
  error_message: string | null;
  records_processed: number;
  records_failed: number;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
  expires_at: string | null;
  download_available: boolean;
};

export type WorkspacePortabilityJobList = {
  items: WorkspacePortabilityJob[];
  total: number;
  limit: number;
  offset: number;
};

export type CreateWorkspaceExportRequest = {
  sections: WorkspaceExportSection[];
  from?: string | null;
  to?: string | null;
  max_rows_per_section?: number;
};

export type CreateWorkspaceImportRequest = {
  artifact: Record<string, unknown>;
  apply: boolean;
};

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
