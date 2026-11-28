import type { Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

/**
 * Admin freshness threshold policy API client (F311).
 *
 * Endpoints:
 *   GET  /admin/settings/freshness-thresholds
 *   PATCH /admin/settings/freshness-thresholds
 */

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

export type FreshnessThresholdsResponse = Served<
  Schemas["FreshnessThresholdsResponse"]
>;

export type PatchFreshnessThresholdsRequest =
  Schemas["PatchFreshnessThresholdsRequest"];

export async function getFreshnessThresholds(): Promise<FreshnessThresholdsResponse> {
  return apiRequest<FreshnessThresholdsResponse>(
    "/admin/settings/freshness-thresholds",
  );
}

export async function patchFreshnessThresholds(
  data: PatchFreshnessThresholdsRequest,
): Promise<FreshnessThresholdsResponse> {
  return apiRequest<FreshnessThresholdsResponse>(
    "/admin/settings/freshness-thresholds",
    { method: "PATCH", body: JSON.stringify(data) },
  );
}
