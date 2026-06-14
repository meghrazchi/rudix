import { apiRequest } from "@/lib/api/request";

export type SyncJobStatus = "active" | "paused" | "disabled";
export type SyncRunStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";
export type SyncTriggerType = "manual" | "scheduled";

export type SyncJob = {
  id: string;
  organization_id: string;
  connection_id: string;
  external_source_id: string | null;
  collection_id: string | null;
  name: string;
  status: SyncJobStatus;
  schedule: {
    type: string;
    interval_minutes?: number;
  };
  last_run_at: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
};

export type SyncRun = {
  id: string;
  organization_id: string;
  sync_job_id: string;
  connection_id: string;
  external_source_id: string | null;
  status: SyncRunStatus;
  trigger_type: SyncTriggerType;
  sync_version: number;
  started_at: string | null;
  completed_at: string | null;
  items_seen: number;
  items_upserted: number;
  items_deleted: number;
  cursor_before: Record<string, unknown>;
  cursor_after: Record<string, unknown>;
  error_message: string | null;
  error_details: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type SyncJobsListResponse = {
  items: SyncJob[];
  total: number;
};

export type SyncRunsListResponse = {
  items: SyncRun[];
  total: number;
};

export type TriggerSyncNowResponse = {
  sync_run_id: string;
  status: string;
  message: string;
};

export type CreateSyncJobPayload = {
  name: string;
  external_source_id?: string;
  collection_id?: string;
  schedule?: {
    type: "interval" | "manual_only";
    interval_minutes?: number;
  };
};

export async function createSyncJob(
  connectionId: string,
  payload: CreateSyncJobPayload,
): Promise<SyncJob> {
  return apiRequest<SyncJob>(`/connectors/${connectionId}/sync-jobs`, {
    method: "POST",
    json: payload,
  });
}

export async function listSyncJobs(
  connectionId: string,
): Promise<SyncJobsListResponse> {
  return apiRequest<SyncJobsListResponse>(
    `/connectors/${connectionId}/sync-jobs`,
  );
}

export async function getSyncJob(
  connectionId: string,
  jobId: string,
): Promise<SyncJob> {
  return apiRequest<SyncJob>(`/connectors/${connectionId}/sync-jobs/${jobId}`);
}

export async function updateSyncJobStatus(
  connectionId: string,
  jobId: string,
  status: SyncJobStatus,
): Promise<SyncJob> {
  return apiRequest<SyncJob>(`/connectors/${connectionId}/sync-jobs/${jobId}`, {
    method: "PATCH",
    json: { status },
  });
}

export async function triggerSyncNow(
  connectionId: string,
  jobId?: string,
): Promise<TriggerSyncNowResponse> {
  const qs = jobId ? `?job_id=${encodeURIComponent(jobId)}` : "";
  return apiRequest<TriggerSyncNowResponse>(
    `/connectors/${connectionId}/sync/now${qs}`,
    { method: "POST" },
  );
}

export async function retrySyncRun(
  runId: string,
): Promise<TriggerSyncNowResponse> {
  return apiRequest<TriggerSyncNowResponse>(
    `/connectors/sync-runs/${runId}/retry`,
    { method: "POST" },
  );
}

export async function listSyncRuns(
  connectionId: string,
  limit = 20,
): Promise<SyncRunsListResponse> {
  return apiRequest<SyncRunsListResponse>(
    `/connectors/${connectionId}/sync-runs?limit=${limit}`,
  );
}

export async function getSyncRun(runId: string): Promise<SyncRun> {
  return apiRequest<SyncRun>(`/connectors/sync-runs/${runId}`);
}

export async function cancelSyncRun(runId: string): Promise<SyncRun> {
  return apiRequest<SyncRun>(`/connectors/sync-runs/${runId}/cancel`, {
    method: "POST",
  });
}
