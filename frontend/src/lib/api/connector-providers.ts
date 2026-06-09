import { apiRequest } from "@/lib/api/request";

export type ConnectorAuthType =
  | "oauth2"
  | "api_token"
  | "service_account"
  | "basic"
  | "none";

export type ConnectorCapabilityKey =
  | "webhooks"
  | "attachments"
  | "comments"
  | "folders"
  | "acls"
  | "delta_sync"
  | "rate_limits"
  | "export_formats"
  | "files"
  | "deletions"
  | "deep_links";

export type ProviderRateLimit = {
  name: string;
  max_requests: number;
  window_seconds: number;
  burst: number | null;
};

export type ProviderExportFormat = {
  format: string;
  mime_type: string;
};

export type ProviderConfigSchemaField = {
  type: "string" | "boolean" | "array" | "integer" | "number";
  title?: string | null;
  description?: string | null;
  format?: string | null;
  items?: { type: string } | null;
};

export type ProviderConfigSchema = {
  type: "object";
  properties: Record<string, ProviderConfigSchemaField>;
  required?: string[];
  additionalProperties?: boolean;
};

export type ProviderCapabilities = {
  auth_type: ConnectorAuthType;
  capabilities: ConnectorCapabilityKey[];
  rate_limits: ProviderRateLimit[];
  export_formats: ProviderExportFormat[];
  max_page_size: number | null;
  notes: string | null;
};

export type ProviderSummary = {
  key: string;
  display_name: string;
  enabled_by_default: boolean;
  has_oauth: boolean;
  capabilities: ProviderCapabilities;
  config_schema: ProviderConfigSchema;
};

export type ProvidersListResponse = {
  items: ProviderSummary[];
  total: number;
};

export async function listProviders(): Promise<ProvidersListResponse> {
  return apiRequest<ProvidersListResponse>("/connectors/providers");
}

export async function getProvider(
  providerKey: string,
): Promise<ProviderSummary> {
  return apiRequest<ProviderSummary>(
    `/connectors/providers/${encodeURIComponent(providerKey)}`,
  );
}

export function hasCapability(
  provider: ProviderSummary,
  capability: ConnectorCapabilityKey,
): boolean {
  return provider.capabilities.capabilities.includes(capability);
}
