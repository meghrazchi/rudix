import type { Overlay, Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

export type CapabilitySummary = Served<Schemas["CapabilitySummary"]>;

export type ProviderCard = Served<Schemas["ProviderCard"]>;

export type ModelProviderDiagnosticsResponse = Served<
  Schemas["ModelProviderDiagnosticsResponse"]
>;

export type TestProviderRequest = Schemas["TestProviderRequest"];

export type ProviderTestStatus =
  | "ok"
  | "configuration_error"
  | "unknown_provider"
  | "unreachable"
  | "timeout"
  | "error";

export type TestProviderResponse = Overlay<
  Served<Schemas["TestProviderResponse"]>,
  { status: ProviderTestStatus }
>;

export async function getModelProviderDiagnostics(): Promise<ModelProviderDiagnosticsResponse> {
  return apiRequest<ModelProviderDiagnosticsResponse>("/admin/model-providers");
}

export async function testModelProviderConnection(
  payload: TestProviderRequest,
): Promise<TestProviderResponse> {
  return apiRequest<TestProviderResponse>("/admin/model-providers/test", {
    method: "POST",
    body: JSON.stringify(payload),
    headers: { "Content-Type": "application/json" },
  });
}
