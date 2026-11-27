import type { Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

export type TrustAnalyticsDateRange = Served<
  Schemas["TrustAnalyticsDateRange"]
>;

export type TrustDistribution = Served<Schemas["TrustDistribution"]>;

export type WarningBreakdown = Served<Schemas["WarningBreakdown"]>;

export type TrustTrendPoint = Served<Schemas["TrustTrendPoint"]>;

export type LangfuseIntegrationStatus = Served<
  Schemas["LangfuseIntegrationStatus"]
>;

export type TrustAnalyticsResponse = Served<Schemas["TrustAnalyticsResponse"]>;

export type TrustAnalyticsQuery = {
  from?: string;
  to?: string;
};

export async function getTrustAnalytics(
  query: TrustAnalyticsQuery = {},
): Promise<TrustAnalyticsResponse> {
  const params = new URLSearchParams();
  if (query.from) params.set("from", query.from);
  if (query.to) params.set("to", query.to);
  const qs = params.toString();
  return apiRequest<TrustAnalyticsResponse>(
    `/admin/trust-analytics${qs ? `?${qs}` : ""}`,
  );
}
