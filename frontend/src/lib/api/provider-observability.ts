import type { Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

export type SloSuggestion = Served<Schemas["SloSuggestion"]>;

export type ProviderHealthCard = Served<Schemas["ProviderHealthCard"]>;

export type ProviderObservabilityRange = Served<
  Schemas["ProviderObservabilityRange"]
>;

export type ProviderObservabilitySnapshot = Served<
  Schemas["ProviderObservabilitySnapshot"]
>;

export type ProviderObservabilityQuery = {
  from?: string;
  to?: string;
};

export async function getProviderObservabilitySnapshot(
  query?: ProviderObservabilityQuery,
): Promise<ProviderObservabilitySnapshot> {
  const params = new URLSearchParams();
  if (query?.from) params.set("from", query.from);
  if (query?.to) params.set("to", query.to);
  const qs = params.toString();
  return apiRequest<ProviderObservabilitySnapshot>(
    `/admin/provider-observability${qs ? `?${qs}` : ""}`,
  );
}
