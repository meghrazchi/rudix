import type { Overlay, Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

export type GovernanceToolSummary = Served<Schemas["GovernanceToolSummary"]>;

// The server sends the cost limit as a decimal string; the editor holds a number while typing.
export type GovernanceBudgetConfig = Overlay<
  Served<Schemas["GovernanceBudgetConfig-Output"]>,
  { max_total_cost_usd: number | string | null }
>;

export type ExternalMcpServerPolicy = Served<
  Schemas["ExternalMCPServerPolicy"]
>;

export type ProviderSecurityPolicy = Served<Schemas["ProviderSecurityPolicy"]>;

export const DEFAULT_PROVIDER_SECURITY: ProviderSecurityPolicy = {
  local_only_mode: false,
  cloud_fallback_allowed: true,
  allowed_provider_profiles: [],
  admin_only_model_selection: true,
  retention_warning_acknowledged: false,
};

export type GovernancePolicyState = Overlay<
  Served<Schemas["GovernancePolicyState"]>,
  { budgets: GovernanceBudgetConfig }
>;

export type GovernanceMcpStatus = {
  feature_enable_mcp: boolean;
  mcp_transport: string;
  mcp_http_path: string;
  mcp_http_host: string;
  mcp_http_port: number;
  mcp_auth_required: boolean;
  mcp_rate_limit_enabled: boolean;
  feature_enable_external_mcp_connectors: boolean;
  configured_global_external_servers: number;
};

export type GovernancePolicyResponse = Overlay<
  Served<Schemas["GovernancePolicyResponse"]>,
  { policy: GovernancePolicyState }
>;

export type GovernancePolicyUpdateRequest =
  Schemas["GovernancePolicyUpdateRequest"];

export type GovernancePolicyUpdateResponse = Overlay<
  Served<Schemas["GovernancePolicyUpdateResponse"]>,
  { policy: GovernancePolicyState }
>;

export async function getGovernancePolicy(): Promise<GovernancePolicyResponse> {
  return apiRequest<GovernancePolicyResponse>("/admin/governance");
}

export async function updateGovernancePolicy(
  payload: GovernancePolicyUpdateRequest,
): Promise<GovernancePolicyUpdateResponse> {
  return apiRequest<GovernancePolicyUpdateResponse>("/admin/governance", {
    method: "PATCH",
    json: payload,
  });
}
