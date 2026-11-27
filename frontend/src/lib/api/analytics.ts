import type { Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

export type AnalyticsDateRange = Served<Schemas["AnalyticsDateRange"]>;

export type AnalyticsActivationSummary = Served<
  Schemas["AnalyticsActivationSummaryResponse"]
>;

export type AnalyticsSummaryResponse = Served<
  Schemas["AnalyticsSummaryResponse"]
>;

export type AnalyticsSummaryQuery = {
  from?: string;
  to?: string;
};

export async function getAnalyticsSummary(
  query: AnalyticsSummaryQuery = {},
): Promise<AnalyticsSummaryResponse> {
  return apiRequest<AnalyticsSummaryResponse>("/analytics/summary", {
    query,
  });
}
