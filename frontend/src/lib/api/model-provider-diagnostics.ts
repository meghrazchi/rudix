import { apiRequest } from "@/lib/api/request";

export type CapabilitySummary = {
  context_window: number | null;
  supports_json_mode: boolean;
  supports_tool_calling: boolean;
  supports_streaming: boolean;
  is_embedding_model: boolean;
  embedding_dimension: number | null;
  cost_behavior: string;
};

export type ProviderCard = {
  provider_key: string;
  provider_type: string;
  model_name: string;
  is_configured: boolean;
  task_assignments: string[];
  capability: CapabilitySummary | null;
  reindex_required: boolean;
};

export type ModelProviderDiagnosticsResponse = {
  providers: ProviderCard[];
};

export type TestProviderRequest = {
  provider_key: "chat" | "embeddings";
};

export type ProviderTestStatus =
  | "ok"
  | "configuration_error"
  | "unknown_provider"
  | "unreachable"
  | "timeout"
  | "error";

export type TestProviderResponse = {
  provider_key: string;
  provider_type: string;
  model_name: string;
  status: ProviderTestStatus;
  latency_ms: number | null;
  error_code: string | null;
  error_message: string | null;
};

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
