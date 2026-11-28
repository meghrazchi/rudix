import type { Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

export type IncidentStatus =
  | "investigating"
  | "identified"
  | "monitoring"
  | "resolved";
export type IncidentSeverity = "critical" | "high" | "medium" | "low";

export type IncidentNoteEntry = Served<Schemas["IncidentNoteEntry"]>;

export type IncidentSummary = Served<Schemas["IncidentSummary"]>;

export type IncidentDetail = Served<Schemas["IncidentDetail"]>;

export type IncidentsListResponse = Served<Schemas["IncidentsListResponse"]>;

export type ServiceStatusBanner = Served<Schemas["ServiceStatusBanner"]>;

export type ServiceStatusSnapshot = Served<Schemas["ServiceStatusSnapshot"]>;

export type IncidentsQuery = {
  status?: IncidentStatus;
  severity?: IncidentSeverity;
  active_only?: boolean;
  page?: number;
  page_size?: number;
};

export type CreateIncidentRequest = Schemas["CreateIncidentRequest"];

export type UpdateIncidentRequest = Schemas["UpdateIncidentRequest"];

export type AddIncidentNoteRequest = Schemas["AddIncidentNoteRequest"];

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
  if (query?.page_size != null)
    params.set("page_size", String(query.page_size));
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
