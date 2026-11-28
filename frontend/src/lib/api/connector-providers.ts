import { apiRequest } from "@/lib/api/request";
import type { Overlay } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

type Schemas = components["schemas"];

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

export type ProviderRateLimit = Schemas["ProviderRateLimitResponse"];

export type ProviderExportFormat = Schemas["ProviderExportFormatResponse"];

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

// The schema types these as free-form strings and objects; the UI narrows them.
export type ProviderCapabilities = Overlay<
  Schemas["ProviderCapabilitiesResponse"],
  { auth_type: ConnectorAuthType; capabilities: ConnectorCapabilityKey[] }
>;

export type ProviderSummary = Overlay<
  Schemas["ProviderSummaryResponse"],
  { capabilities: ProviderCapabilities; config_schema: ProviderConfigSchema }
>;

export type ProvidersListResponse = Overlay<
  Schemas["ProvidersListResponse"],
  { items: ProviderSummary[] }
>;

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
