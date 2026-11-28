import type { Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

export type PublicComponentState =
  | "operational"
  | "degraded"
  | "outage"
  | "maintenance"
  | "unknown";

export type PublicStatusComponent = Served<Schemas["PublicStatusComponent"]>;

export type PublicStatusIncident = Served<Schemas["PublicStatusIncident"]>;

export type PublicStatusSnapshot = Served<Schemas["PublicStatusSnapshot"]>;

export async function getPublicStatusSnapshot(): Promise<PublicStatusSnapshot> {
  return apiRequest<PublicStatusSnapshot>("/status", {
    attachAuth: false,
    attachOrganizationId: false,
    cache: "no-store",
    retry: { maxRetries: 1 },
  });
}
