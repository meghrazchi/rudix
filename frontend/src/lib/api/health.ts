import { apiRequest } from "@/lib/api/request";

export type HealthDependency = {
  ok: boolean;
  detail: string | null;
  metadata: Record<string, string | number | boolean | null>;
};

export type HealthResponse = {
  status: string;
  timestamp: string;
  dependencies: Record<string, HealthDependency>;
  failed_dependencies: string[];
};

export async function getHealth(): Promise<HealthResponse> {
  return apiRequest<HealthResponse>("/health", {
    attachAuth: false,
    attachOrganizationId: false,
    retry: { maxRetries: 1 },
  });
}

export async function getReadiness(): Promise<HealthResponse> {
  return apiRequest<HealthResponse>("/ready", {
    attachAuth: false,
    attachOrganizationId: false,
    retry: { maxRetries: 1 },
  });
}

export async function getConfigSnapshot(): Promise<Record<string, unknown>> {
  return apiRequest<Record<string, unknown>>("/configz", {
    attachAuth: false,
    attachOrganizationId: false,
  });
}

export type SentryTestResponse = {
  status: string;
  event_id: string | null;
  sentry_enabled: boolean;
};

export async function createSentryTestEvent(): Promise<SentryTestResponse> {
  return apiRequest<SentryTestResponse>("/sentry-test", {
    method: "POST",
    attachAuth: false,
    attachOrganizationId: false,
  });
}
