import { apiRequest } from "@/lib/api/request";

export type PublicComponentState =
  | "operational"
  | "degraded"
  | "outage"
  | "maintenance"
  | "unknown";

export type PublicStatusComponent = {
  key: string;
  label: string;
  status: PublicComponentState;
  summary: string;
  affected_services: string[];
  updated_at: string | null;
};

export type PublicStatusIncident = {
  title: string;
  status: string;
  severity: string;
  kind: "incident" | "maintenance";
  affected_services: string[];
  message: string | null;
  started_at: string;
  resolved_at: string | null;
};

export type PublicStatusSnapshot = {
  generated_at: string;
  overall_status: PublicComponentState;
  headline: string;
  summary: string;
  components: PublicStatusComponent[];
  current_incidents: PublicStatusIncident[];
  scheduled_maintenance: PublicStatusIncident[];
  recent_history: PublicStatusIncident[];
  uptime_notice: string;
};

export async function getPublicStatusSnapshot(): Promise<PublicStatusSnapshot> {
  return apiRequest<PublicStatusSnapshot>("/status", {
    attachAuth: false,
    attachOrganizationId: false,
    cache: "no-store",
    retry: { maxRetries: 1 },
  });
}
