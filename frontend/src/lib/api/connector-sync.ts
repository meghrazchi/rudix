import { apiRequest } from "@/lib/api/request";
import type { Overlay, WithOptional } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

type Schemas = components["schemas"];

export type SyncJobStatus = "active" | "paused" | "disabled";
export type SyncRunStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";
export type SyncTriggerType = "manual" | "scheduled";

export type SyncJob = Overlay<
  Schemas["SyncJobResponse"],
  {
    status: SyncJobStatus;
    schedule: { type: string; interval_minutes?: number };
  }
>;

// pages_committed has a server default; the status vocabularies are narrowed for the UI.
export type SyncRun = Overlay<
  WithOptional<Schemas["SyncRunResponse"], "pages_committed">,
  { status: SyncRunStatus; trigger_type: SyncTriggerType }
>;

export type SyncJobsListResponse = Overlay<
  Schemas["SyncJobsListResponse"],
  { items: SyncJob[] }
>;

export type SyncRunsListResponse = Overlay<
  Schemas["SyncRunsListResponse"],
  { items: SyncRun[] }
>;

export type TriggerSyncNowResponse = Schemas["TriggerSyncNowResponse"];

export type CreateSyncJobPayload = Schemas["CreateSyncJobRequest"];

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

// ---------------------------------------------------------------------------
// Force full resync
// ---------------------------------------------------------------------------

export type ForceFullResyncResponse = Schemas["ForceFullResyncResponse"];

export async function triggerFullResync(
  connectionId: string,
  jobId?: string,
): Promise<ForceFullResyncResponse> {
  const qs = jobId ? `?job_id=${encodeURIComponent(jobId)}` : "";
  return apiRequest<ForceFullResyncResponse>(
    `/connectors/${connectionId}/sync/full${qs}`,
    { method: "POST" },
  );
}

// ---------------------------------------------------------------------------
// Conflicts
// ---------------------------------------------------------------------------

export type SyncConflictStatus = "open" | "resolved" | "dismissed";
export type SyncConflictType =
  | "acl_changed"
  | "renamed"
  | "moved"
  | "permission_revoked";

export type SyncConflict = Schemas["SyncConflictResponse"];

export type SyncConflictsListResponse = Schemas["SyncConflictsListResponse"];

export type ResolveConflictPayload = Schemas["ResolveConflictRequest"];

export async function listSyncConflicts(
  connectionId: string,
  conflictStatus?: SyncConflictStatus,
  limit = 50,
): Promise<SyncConflictsListResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (conflictStatus) params.set("status", conflictStatus);
  return apiRequest<SyncConflictsListResponse>(
    `/connectors/${connectionId}/conflicts?${params}`,
  );
}

export async function resolveSyncConflict(
  connectionId: string,
  conflictId: string,
  payload: ResolveConflictPayload,
): Promise<SyncConflict> {
  return apiRequest<SyncConflict>(
    `/connectors/${connectionId}/conflicts/${conflictId}/resolve`,
    { method: "POST", json: payload },
  );
}
