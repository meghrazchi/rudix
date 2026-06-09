import { apiRequest } from "@/lib/api/request";

export type GovernanceToolSummary = {
  name: string;
  capability: string;
  effect_policy: "read_only" | "side_effect";
  surfaces: Array<"api" | "mcp">;
  required_roles: string[];
  approval_required: boolean;
};

export type GovernanceBudgetConfig = {
  max_steps: number;
  max_tool_calls_per_run: number;
  max_tool_timeout_ms: number;
  max_tool_input_bytes: number;
  max_tool_output_bytes: number;
  max_tool_retry_attempts: number;
  max_total_tokens?: number | null;
  max_total_cost_usd?: number | null;
};

export type ExternalMcpServerPolicy = {
  server_id: string;
  enabled: boolean;
  transport: "streamable_http";
  base_url: string;
  auth_type: "none" | "bearer" | "header";
  auth_header_name?: string | null;
  auth_secret_ref?: string | null;
  allow_tools: string[];
  read_only_tools: string[];
  side_effect_tools: string[];
  required_roles: string[];
  expose_on_mcp_surface: boolean;
  approval_required_for_side_effect: boolean;
};

export type ProviderSecurityPolicy = {
  local_only_mode: boolean;
  cloud_fallback_allowed: boolean;
  allowed_provider_profiles: string[];
  admin_only_model_selection: boolean;
  retention_warning_acknowledged: boolean;
};

export const DEFAULT_PROVIDER_SECURITY: ProviderSecurityPolicy = {
  local_only_mode: false,
  cloud_fallback_allowed: true,
  allowed_provider_profiles: [],
  admin_only_model_selection: true,
  retention_warning_acknowledged: false,
};

export type GovernancePolicyState = {
  agentic_mode_enabled: boolean;
  mcp_exposure_enabled: boolean;
  allow_side_effect_tools: boolean;
  allowed_tool_names: string[];
  budgets: GovernanceBudgetConfig;
  external_mcp_servers: ExternalMcpServerPolicy[];
  provider_security: ProviderSecurityPolicy;
};

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

export type GovernancePolicyResponse = {
  organization_id: string;
  policy: GovernancePolicyState;
  mcp_status: GovernanceMcpStatus;
  tool_catalog: GovernanceToolSummary[];
  warnings: string[];
  policy_updated_at?: string | null;
  policy_updated_by_user_id?: string | null;
};

export type GovernancePolicyUpdateRequest = {
  agentic_mode_enabled?: boolean;
  mcp_exposure_enabled?: boolean;
  allow_side_effect_tools?: boolean;
  allowed_tool_names?: string[];
  budgets?: GovernanceBudgetConfig;
  external_mcp_servers?: ExternalMcpServerPolicy[];
  side_effect_warning_acknowledged?: boolean;
  provider_security?: Partial<ProviderSecurityPolicy>;
  cloud_fallback_warning_acknowledged?: boolean;
};

export type GovernancePolicyUpdateResponse = {
  organization_id: string;
  policy: GovernancePolicyState;
  warnings: string[];
  updated_at: string;
  updated_by_user_id?: string | null;
  audit_recorded: boolean;
  changed_fields: string[];
};

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
