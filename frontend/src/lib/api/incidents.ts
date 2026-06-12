import { apiRequest } from "@/lib/api/request";

export type IncidentStatus =
  | "investigating"
  | "identified"
  | "monitoring"
  | "resolved";
export type IncidentSeverity = "critical" | "high" | "medium" | "low";

export type IncidentNoteEntry = {
  id: string;
  note: string;
  status_change: string | null;
  created_by_id: string | null;
  created_at: string;
};

export type IncidentSummary = {
  id: string;
  organization_id: string;
  title: string;
  status: IncidentStatus;
  severity: IncidentSeverity;
  affected_services: string[];
  message: string | null;
  is_public: boolean;
  started_at: string;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
};

export type IncidentDetail = IncidentSummary & {
  notes: IncidentNoteEntry[];
};

export type IncidentsListResponse = {
  items: IncidentSummary[];
  total: number;
  page: number;
  page_size: number;
};

export type ServiceStatusBanner = {
  has_active_incident: boolean;
  has_active_maintenance: boolean;
  active_incident_count: number;
  banner_message: string | null;
  highest_severity: string | null;
};

export type ServiceStatusSnapshot = {
  organization_id: string;
  generated_at: string;
  active_incidents: IncidentSummary[];
  recently_resolved: IncidentSummary[];
  open_failed_job_count: number;
  banner: ServiceStatusBanner;
};

export type IncidentsQuery = {
  status?: IncidentStatus;
  severity?: IncidentSeverity;
  active_only?: boolean;
  page?: number;
  page_size?: number;
};

export type CreateIncidentRequest = {
  title: string;
  severity?: IncidentSeverity;
  affected_services?: string[];
  message?: string | null;
  is_public?: boolean;
  started_at?: string | null;
};

export type UpdateIncidentRequest = {
  title?: string;
  status?: IncidentStatus;
  severity?: IncidentSeverity;
  affected_services?: string[];
  message?: string | null;
  is_public?: boolean;
  resolved_at?: string | null;
};

export type AddIncidentNoteRequest = {
  note: string;
  status_change?: IncidentStatus | null;
};

export async function getStatusSnapshot(): Promise<ServiceStatusSnapshot> {
  return apiRequest<ServiceStatusSnapshot>("/admin/status");
}

export async function getStatusBanner(): Promise<ServiceStatusBanner> {
  return apiRequest<ServiceStatusBanner>("/status/banner");
}

export async function listIncidents(
  query?: IncidentsQuery,
): Promise<IncidentsListResponse> {
  const params = new URLSearchParams();
  if (query?.status) params.set("status", query.status);
  if (query?.severity) params.set("severity", query.severity);
  if (query?.active_only) params.set("active_only", "true");
  if (query?.page != null) params.set("page", String(query.page));
  if (query?.page_size != null) params.set("page_size", String(query.page_size));
  const qs = params.toString();
  return apiRequest<IncidentsListResponse>(
    `/admin/incidents${qs ? `?${qs}` : ""}`,
  );
}

export async function getIncident(incidentId: string): Promise<IncidentDetail> {
  return apiRequest<IncidentDetail>(`/admin/incidents/${incidentId}`);
}

export async function createIncident(
  body: CreateIncidentRequest,
): Promise<IncidentDetail> {
  return apiRequest<IncidentDetail>("/admin/incidents", {
    method: "POST",
    json: body,
  });
}

export async function updateIncident(
  incidentId: string,
  body: UpdateIncidentRequest,
): Promise<IncidentDetail> {
  return apiRequest<IncidentDetail>(`/admin/incidents/${incidentId}`, {
    method: "PATCH",
    json: body,
  });
}

export async function addIncidentNote(
  incidentId: string,
  body: AddIncidentNoteRequest,
): Promise<IncidentDetail> {
  return apiRequest<IncidentDetail>(`/admin/incidents/${incidentId}/notes`, {
    method: "POST",
    json: body,
  });
}
