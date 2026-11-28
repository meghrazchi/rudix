import type { Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

export type GraphObservabilityRange = Served<
  Schemas["GraphObservabilityRange"]
>;

export type GraphAlertLevel = "warning" | "critical";

export type GraphAlertItem = Served<Schemas["GraphAlertItem"]>;

export type GraphExtractionMetrics = Served<Schemas["GraphExtractionMetrics"]>;

export type GraphEntityTypeCount = Served<Schemas["GraphEntityTypeCount"]>;

export type GraphEntityMetrics = Served<Schemas["GraphEntityMetrics"]>;

export type GraphRelationMetrics = Served<Schemas["GraphRelationMetrics"]>;

export type GraphQueryMetrics = Served<Schemas["GraphQueryMetrics"]>;

export type GraphAlertThresholds = Served<Schemas["GraphAlertThresholds"]>;

export type GraphTrendPoint = Served<Schemas["GraphTrendPoint"]>;

export type GraphObservabilitySnapshot = Served<
  Schemas["GraphObservabilitySnapshot"]
>;

export type GraphObservabilityQuery = {
  from?: string;
  to?: string;
};

export async function getGraphObservabilitySnapshot(
  query?: GraphObservabilityQuery,
): Promise<GraphObservabilitySnapshot> {
  const params = new URLSearchParams();
  if (query?.from) params.set("from", query.from);
  if (query?.to) params.set("to", query.to);
  const qs = params.toString();
  return apiRequest<GraphObservabilitySnapshot>(
    `/admin/graph/observability${qs ? `?${qs}` : ""}`,
  );
}
