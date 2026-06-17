import { apiRequest } from "@/lib/api/request";

export type OrgMCPPolicy = {
  organization_id: string;
  enabled: boolean;
  read_only: boolean;
  allowed_tools: string[] | null;
  capabilities_owner: string[] | null;
  capabilities_admin: string[] | null;
  capabilities_member: string[] | null;
  capabilities_viewer: string[] | null;
  rate_limit_enabled: boolean;
  rate_limit_requests: number;
  rate_limit_window_seconds: number;
  // F176 trust and exposure controls
  allowed_resources: string[] | null;
  allowed_prompts: string[] | null;
  allowed_collections: string[] | null;
  allowed_roles: string[] | null;
  redact_document_text: boolean;
  max_chunk_chars: number | null;
  max_request_bytes: number | null;
  max_response_bytes: number | null;
  updated_by_user_id: string | null;
  updated_at: string;
};

export type UpdateMCPPolicyRequest = {
  enabled?: boolean | null;
  read_only?: boolean | null;
  allowed_tools?: string[] | null;
  capabilities_owner?: string[] | null;
  capabilities_admin?: string[] | null;
  capabilities_member?: string[] | null;
  capabilities_viewer?: string[] | null;
  rate_limit_enabled?: boolean | null;
  rate_limit_requests?: number | null;
  rate_limit_window_seconds?: number | null;
  // F176 trust and exposure controls
  allowed_resources?: string[] | null;
  allowed_prompts?: string[] | null;
  allowed_collections?: string[] | null;
  allowed_roles?: string[] | null;
  redact_document_text?: boolean | null;
  max_chunk_chars?: number | null;
  max_request_bytes?: number | null;
  max_response_bytes?: number | null;
};

export type MCPDependencyStatus = {
  ok: boolean;
  detail: string | null;
};

export type MCPStatusResponse = {
  feature_enabled: boolean;
  auth_required: boolean;
  transport: string;
  server_name: string;
  rate_limit_enabled: boolean;
  rate_limit_requests: number;
  rate_limit_window_seconds: number;
  http_host: string;
  http_port: number;
  http_path: string;
  dependencies: Record<string, MCPDependencyStatus>;
  failed_dependencies: string[];
};

export type MCPToolInfo = {
  name: string;
  public_name: string;
  description: string;
  capability: string;
  deprecated_alias: boolean;
};

export type MCPToolListResponse = {
  items: MCPToolInfo[];
  total: number;
};

export type MCPAuditEvent = {
  id: string;
  action: string;
  user_id: string | null;
  resource_type: string | null;
  resource_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type MCPAuditEventListResponse = {
  items: MCPAuditEvent[];
  total: number;
};

function normalizePolicy(value: unknown): OrgMCPPolicy {
  const raw =
    value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return {
    organization_id:
      typeof raw.organization_id === "string" ? raw.organization_id : "",
    enabled: raw.enabled === true,
    read_only: raw.read_only !== false,
    allowed_tools: Array.isArray(raw.allowed_tools)
      ? (raw.allowed_tools as unknown[]).filter(
          (t): t is string => typeof t === "string",
        )
      : null,
    capabilities_owner: Array.isArray(raw.capabilities_owner)
      ? (raw.capabilities_owner as unknown[]).filter(
          (c): c is string => typeof c === "string",
        )
      : null,
    capabilities_admin: Array.isArray(raw.capabilities_admin)
      ? (raw.capabilities_admin as unknown[]).filter(
          (c): c is string => typeof c === "string",
        )
      : null,
    capabilities_member: Array.isArray(raw.capabilities_member)
      ? (raw.capabilities_member as unknown[]).filter(
          (c): c is string => typeof c === "string",
        )
      : null,
    capabilities_viewer: Array.isArray(raw.capabilities_viewer)
      ? (raw.capabilities_viewer as unknown[]).filter(
          (c): c is string => typeof c === "string",
        )
      : null,
    rate_limit_enabled: raw.rate_limit_enabled !== false,
    rate_limit_requests:
      typeof raw.rate_limit_requests === "number" ? raw.rate_limit_requests : 30,
    rate_limit_window_seconds:
      typeof raw.rate_limit_window_seconds === "number"
        ? raw.rate_limit_window_seconds
        : 60,
    allowed_resources: Array.isArray(raw.allowed_resources)
      ? (raw.allowed_resources as unknown[]).filter(
          (r): r is string => typeof r === "string",
        )
      : null,
    allowed_prompts: Array.isArray(raw.allowed_prompts)
      ? (raw.allowed_prompts as unknown[]).filter(
          (p): p is string => typeof p === "string",
        )
      : null,
    allowed_collections: Array.isArray(raw.allowed_collections)
      ? (raw.allowed_collections as unknown[]).filter(
          (c): c is string => typeof c === "string",
        )
      : null,
    allowed_roles: Array.isArray(raw.allowed_roles)
      ? (raw.allowed_roles as unknown[]).filter(
          (r): r is string => typeof r === "string",
        )
      : null,
    redact_document_text: raw.redact_document_text !== false,
    max_chunk_chars:
      typeof raw.max_chunk_chars === "number" ? raw.max_chunk_chars : null,
    max_request_bytes:
      typeof raw.max_request_bytes === "number" ? raw.max_request_bytes : null,
    max_response_bytes:
      typeof raw.max_response_bytes === "number" ? raw.max_response_bytes : null,
    updated_by_user_id:
      typeof raw.updated_by_user_id === "string"
        ? raw.updated_by_user_id
        : null,
    updated_at: typeof raw.updated_at === "string" ? raw.updated_at : "",
  };
}

function normalizeStatus(value: unknown): MCPStatusResponse {
  const raw =
    value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  const deps: Record<string, MCPDependencyStatus> = {};
  const rawDeps =
    raw.dependencies && typeof raw.dependencies === "object"
      ? (raw.dependencies as Record<string, unknown>)
      : {};
  for (const [key, dep] of Object.entries(rawDeps)) {
    const d =
      dep && typeof dep === "object" ? (dep as Record<string, unknown>) : {};
    deps[key] = {
      ok: d.ok === true,
      detail: typeof d.detail === "string" ? d.detail : null,
    };
  }
  return {
    feature_enabled: raw.feature_enabled === true,
    auth_required: raw.auth_required === true,
    transport: typeof raw.transport === "string" ? raw.transport : "",
    server_name: typeof raw.server_name === "string" ? raw.server_name : "",
    rate_limit_enabled: raw.rate_limit_enabled !== false,
    rate_limit_requests:
      typeof raw.rate_limit_requests === "number" ? raw.rate_limit_requests : 30,
    rate_limit_window_seconds:
      typeof raw.rate_limit_window_seconds === "number"
        ? raw.rate_limit_window_seconds
        : 60,
    http_host: typeof raw.http_host === "string" ? raw.http_host : "",
    http_port: typeof raw.http_port === "number" ? raw.http_port : 8010,
    http_path: typeof raw.http_path === "string" ? raw.http_path : "/mcp",
    dependencies: deps,
    failed_dependencies: Array.isArray(raw.failed_dependencies)
      ? (raw.failed_dependencies as unknown[]).filter(
          (d): d is string => typeof d === "string",
        )
      : [],
  };
}

function normalizeToolInfo(value: unknown): MCPToolInfo {
  const raw =
    value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return {
    name: typeof raw.name === "string" ? raw.name : "",
    public_name: typeof raw.public_name === "string" ? raw.public_name : "",
    description: typeof raw.description === "string" ? raw.description : "",
    capability: typeof raw.capability === "string" ? raw.capability : "",
    deprecated_alias: raw.deprecated_alias === true,
  };
}

function normalizeAuditEvent(value: unknown): MCPAuditEvent {
  const raw =
    value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return {
    id: typeof raw.id === "string" ? raw.id : "",
    action: typeof raw.action === "string" ? raw.action : "",
    user_id: typeof raw.user_id === "string" ? raw.user_id : null,
    resource_type:
      typeof raw.resource_type === "string" ? raw.resource_type : null,
    resource_id:
      typeof raw.resource_id === "string" ? raw.resource_id : null,
    metadata:
      raw.metadata && typeof raw.metadata === "object"
        ? (raw.metadata as Record<string, unknown>)
        : {},
    created_at: typeof raw.created_at === "string" ? raw.created_at : "",
  };
}

export async function getMCPPolicy(): Promise<OrgMCPPolicy> {
  const payload = await apiRequest<unknown>("/admin/mcp/policy", {
    method: "GET",
    retry: false,
  });
  return normalizePolicy(payload);
}

export async function updateMCPPolicy(
  request: UpdateMCPPolicyRequest,
): Promise<OrgMCPPolicy> {
  const payload = await apiRequest<unknown>("/admin/mcp/policy", {
    method: "PATCH",
    json: request,
    retry: false,
  });
  return normalizePolicy(payload);
}

export async function getMCPStatus(): Promise<MCPStatusResponse> {
  const payload = await apiRequest<unknown>("/admin/mcp/status", {
    method: "GET",
    retry: false,
  });
  return normalizeStatus(payload);
}

export async function listMCPTools(): Promise<MCPToolListResponse> {
  const payload = await apiRequest<unknown>("/admin/mcp/tools", {
    method: "GET",
    retry: false,
  });
  const raw =
    payload && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : {};
  const items = Array.isArray(raw.items)
    ? raw.items.map(normalizeToolInfo)
    : [];
  return { items, total: typeof raw.total === "number" ? raw.total : items.length };
}

export async function listMCPAuditEvents(params?: {
  limit?: number;
  offset?: number;
}): Promise<MCPAuditEventListResponse> {
  const query = new URLSearchParams();
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  const payload = await apiRequest<unknown>(
    `/admin/mcp/audit-events${qs ? `?${qs}` : ""}`,
    { method: "GET", retry: false },
  );
  const raw =
    payload && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : {};
  const items = Array.isArray(raw.items)
    ? raw.items.map(normalizeAuditEvent)
    : [];
  return { items, total: typeof raw.total === "number" ? raw.total : items.length };
}
