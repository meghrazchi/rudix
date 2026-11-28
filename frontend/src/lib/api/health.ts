import type { Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

export type HealthDependency = Served<Schemas["HealthDependency"]>;

export type HealthResponse = Served<Schemas["HealthResponse"]>;

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
