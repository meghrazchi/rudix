import type {
  ExternalMcpServerPolicy,
  GovernancePolicyResponse,
  GovernancePolicyState,
} from "@/lib/api/admin-governance";

export type NewServerFormState = {
  server_id: string;
  base_url: string;
  auth_type: ExternalMcpServerPolicy["auth_type"];
  auth_header_name: string;
  auth_secret_ref: string;
  allow_tools: string;
  read_only_tools: string;
  side_effect_tools: string;
  required_roles: string;
  enabled: boolean;
  expose_on_mcp_surface: boolean;
  approval_required_for_side_effect: boolean;
};

export const DEFAULT_NEW_SERVER: NewServerFormState = {
  server_id: "",
  base_url: "",
  auth_type: "none",
  auth_header_name: "",
  auth_secret_ref: "",
  allow_tools: "",
  read_only_tools: "",
  side_effect_tools: "",
  required_roles: "owner,admin",
  enabled: true,
  expose_on_mcp_surface: false,
  approval_required_for_side_effect: true,
};

export function parseCommaList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

export function formatCommaList(values: string[]): string {
  return values.join(", ");
}

export function parseInteger(value: string): number | null {
  if (!value.trim()) {
    return null;
  }
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) {
    return null;
  }
  return parsed;
}

export function parseDecimal(value: string): number | null {
  if (!value.trim()) {
    return null;
  }
  const parsed = Number.parseFloat(value);
  if (!Number.isFinite(parsed)) {
    return null;
  }
  return parsed;
}

export function clonePolicy(policy: GovernancePolicyState): GovernancePolicyState {
  return {
    ...policy,
    allowed_tool_names: [...policy.allowed_tool_names],
    budgets: { ...policy.budgets },
    external_mcp_servers: policy.external_mcp_servers.map((server) => ({
      ...server,
      allow_tools: [...server.allow_tools],
      read_only_tools: [...server.read_only_tools],
      side_effect_tools: [...server.side_effect_tools],
      required_roles: [...server.required_roles],
    })),
  };
}

export function resolveInitialPolicy(
  currentDraft: GovernancePolicyState | null,
  response: GovernancePolicyResponse | undefined,
): GovernancePolicyState | null {
  if (currentDraft) {
    return currentDraft;
  }
  if (!response) {
    return null;
  }
  return clonePolicy(response.policy);
}
