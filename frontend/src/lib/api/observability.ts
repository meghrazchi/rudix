import type { Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

export type ObservabilityRange = Served<Schemas["ObservabilityRange"]>;

export type ApiMetrics = Served<Schemas["ApiMetrics"]>;

export type LlmModelSummary = Served<Schemas["LlmModelSummary"]>;

export type LlmMetrics = Served<Schemas["LlmMetrics"]>;

export type IndexingMetrics = Served<Schemas["IndexingMetrics"]>;

export type StorageMetrics = Served<Schemas["StorageMetrics"]>;

export type ObservabilitySnapshot = Served<Schemas["ObservabilitySnapshot"]>;

export type ObservabilityQuery = {
  from?: string;
  to?: string;
};

export async function getObservabilitySnapshot(
  query?: ObservabilityQuery,
): Promise<ObservabilitySnapshot> {
  const params = new URLSearchParams();
  if (query?.from) params.set("from", query.from);
  if (query?.to) params.set("to", query.to);
  const qs = params.toString();
  return apiRequest<ObservabilitySnapshot>(
    `/admin/observability${qs ? `?${qs}` : ""}`,
  );
}
