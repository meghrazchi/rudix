import { apiRequest } from "@/lib/api/request";

export type FailedJobStatus = "failed" | "retrying" | "resolved" | "cancelled";

export type FailedJobSummary = {
  id: string;
  organization_id: string;
  task_id: string;
  task_name: string;
  job_type: string;
  status: FailedJobStatus;
  queue_name: string | null;
  error_code: string | null;
  attempt_count: number;
  is_retryable: boolean;
  entity_type: string | null;
  entity_id: string | null;
  last_attempted_at: string | null;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
};

export type FailedJobAuditEntry = {
  id: string;
  action: string;
  performed_by_id: string | null;
  note: string | null;
  created_at: string;
};

export type FailedJobDetail = FailedJobSummary & {
  error_message: string | null;
  metadata_json: Record<string, unknown>;
  audit_log: FailedJobAuditEntry[];
};

export type FailedJobsListResponse = {
  items: FailedJobSummary[];
  total: number;
  page: number;
  page_size: number;
};

export type BulkRetryResponse = {
  queued: string[];
  skipped: string[];
  skip_reasons: Record<string, string>;
};

export type FailedJobsQuery = {
  job_type?: string;
  status?: FailedJobStatus;
  queue_name?: string;
  retryable_only?: boolean;
  page?: number;
  page_size?: number;
};

export async function listFailedJobs(
  query?: FailedJobsQuery,
): Promise<FailedJobsListResponse> {
  const params = new URLSearchParams();
  if (query?.job_type) params.set("job_type", query.job_type);
  if (query?.status) params.set("status", query.status);
  if (query?.queue_name) params.set("queue_name", query.queue_name);
  if (query?.retryable_only) params.set("retryable_only", "true");
  if (query?.page != null) params.set("page", String(query.page));
  if (query?.page_size != null) params.set("page_size", String(query.page_size));
  const qs = params.toString();
  return apiRequest<FailedJobsListResponse>(
    `/admin/failed-jobs${qs ? `?${qs}` : ""}`,
  );
}

export async function getFailedJob(jobId: string): Promise<FailedJobDetail> {
  return apiRequest<FailedJobDetail>(`/admin/failed-jobs/${jobId}`);
}

export async function retryFailedJob(
  jobId: string,
): Promise<FailedJobSummary> {
  return apiRequest<FailedJobSummary>(`/admin/failed-jobs/${jobId}/retry`, {
    method: "POST",
  });
}

export async function bulkRetryFailedJobs(
  jobIds: string[],
): Promise<BulkRetryResponse> {
  return apiRequest<BulkRetryResponse>(`/admin/failed-jobs/bulk-retry`, {
    method: "POST",
    json: { job_ids: jobIds },
  });
}

export async function cancelFailedJob(
  jobId: string,
): Promise<FailedJobSummary> {
  return apiRequest<FailedJobSummary>(`/admin/failed-jobs/${jobId}/cancel`, {
    method: "POST",
  });
}

export async function resolveFailedJob(
  jobId: string,
): Promise<FailedJobSummary> {
  return apiRequest<FailedJobSummary>(`/admin/failed-jobs/${jobId}/resolve`, {
    method: "POST",
  });
}
