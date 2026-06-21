/**
 * Admin freshness threshold policy API client (F311).
 *
 * Endpoints:
 *   GET  /admin/settings/freshness-thresholds
 *   PATCH /admin/settings/freshness-thresholds
 */

import { apiRequest } from "@/lib/api/request";

export type FreshnessThresholdsResponse = {
  organization_id: string;
  /** Days since last review before a document is promoted to 'stale' warning.
   *  null = use per-document stale_after_days or system default (90 days). */
  warn_stale_after_days: number | null;
  /** Days since last review before an 'unreviewed' warning fires.
   *  null = system default (180 days). */
  warn_unreviewed_after_days: number | null;
  /** If true, deprecated/archived/superseded docs are excluded from retrieval. */
  auto_exclude_deprecated: boolean;
  /** If true, expired docs are excluded from retrieval. */
  auto_exclude_expired: boolean;
  /** Optional admin label for this policy. */
  label: string | null;
  updated_at: string | null;
};

export type PatchFreshnessThresholdsRequest = {
  warn_stale_after_days?: number | null;
  warn_unreviewed_after_days?: number | null;
  auto_exclude_deprecated?: boolean;
  auto_exclude_expired?: boolean;
  label?: string | null;
};

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
