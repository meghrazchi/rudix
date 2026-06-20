import { apiRequest } from "@/lib/api/request";

const BASE = "/admin/permissions";

// ── Role matrix types ──────────────────────────────────────────────────────────

export type RoleMatrixEntry = {
  role: string;
  label: string;
  description: string;
  is_builtin: boolean;
  permissions: string[];
  overridden_permissions: string[];
};

export type RoleMatrixResponse = {
  roles: RoleMatrixEntry[];
  all_permissions: string[];
};

export type UpdateRolePermissionsResponse = {
  role: string;
  permissions: string[];
  overridden_permissions: string[];
};

// ── Resource access types ──────────────────────────────────────────────────────

export type ResourceAccessEntry = {
  id: string;
  organization_id: string;
  user_id: string | null;
  role_name: string | null;
  principal_type: string;
  principal_value: string;
  resource_type: string;
  resource_id: string | null;
  action: string;
  status: string;
  expires_at: string | null;
  reason: string | null;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
  kind: "grant" | "deny";
};

export type ResourceAccessListResponse = {
  items: ResourceAccessEntry[];
  total: number;
  page: number;
  page_size: number;
};

export type CreateResourceAccessRequest = {
  principal_type: string;
  principal_value: string;
  resource_type: string;
  resource_id?: string | null;
  action: string;
  expires_at?: string | null;
  reason?: string | null;
};

// ── Normalizers ────────────────────────────────────────────────────────────────

function normalizeRoleMatrixEntry(value: unknown): RoleMatrixEntry {
  const raw =
    value && typeof value === "object"
      ? (value as Record<string, unknown>)
      : {};
  return {
    role: typeof raw.role === "string" ? raw.role : "",
    label: typeof raw.label === "string" ? raw.label : "",
    description: typeof raw.description === "string" ? raw.description : "",
    is_builtin: raw.is_builtin === true,
    permissions: Array.isArray(raw.permissions)
      ? (raw.permissions as unknown[]).filter(
          (p): p is string => typeof p === "string",
        )
      : [],
    overridden_permissions: Array.isArray(raw.overridden_permissions)
      ? (raw.overridden_permissions as unknown[]).filter(
          (p): p is string => typeof p === "string",
        )
      : [],
  };
}

function normalizeResourceAccessEntry(value: unknown): ResourceAccessEntry {
  const raw =
    value && typeof value === "object"
      ? (value as Record<string, unknown>)
      : {};
  return {
    id: typeof raw.id === "string" ? raw.id : "",
    organization_id:
      typeof raw.organization_id === "string" ? raw.organization_id : "",
    user_id: typeof raw.user_id === "string" ? raw.user_id : null,
    role_name: typeof raw.role_name === "string" ? raw.role_name : null,
    principal_type:
      typeof raw.principal_type === "string" ? raw.principal_type : "",
    principal_value:
      typeof raw.principal_value === "string" ? raw.principal_value : "",
    resource_type:
      typeof raw.resource_type === "string" ? raw.resource_type : "",
    resource_id: typeof raw.resource_id === "string" ? raw.resource_id : null,
    action: typeof raw.action === "string" ? raw.action : "",
    status: typeof raw.status === "string" ? raw.status : "",
    expires_at: typeof raw.expires_at === "string" ? raw.expires_at : null,
    reason: typeof raw.reason === "string" ? raw.reason : null,
    created_by_user_id:
      typeof raw.created_by_user_id === "string"
        ? raw.created_by_user_id
        : null,
    created_at: typeof raw.created_at === "string" ? raw.created_at : "",
    updated_at: typeof raw.updated_at === "string" ? raw.updated_at : "",
    kind: raw.kind === "deny" ? "deny" : "grant",
  };
}

// ── API functions ──────────────────────────────────────────────────────────────

export async function getRoleMatrix(): Promise<RoleMatrixResponse> {
  const payload = await apiRequest<unknown>(`${BASE}/role-matrix`, {
    method: "GET",
    retry: false,
  });
  const raw =
    payload && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : {};
  return {
    roles: Array.isArray(raw.roles)
      ? raw.roles.map(normalizeRoleMatrixEntry)
      : [],
    all_permissions: Array.isArray(raw.all_permissions)
      ? (raw.all_permissions as unknown[]).filter(
          (p): p is string => typeof p === "string",
        )
      : [],
  };
}

export async function updateRolePermissions(
  roleName: string,
  permissions: string[],
): Promise<UpdateRolePermissionsResponse> {
  const payload = await apiRequest<unknown>(
    `${BASE}/role-matrix/${encodeURIComponent(roleName)}`,
    { method: "PATCH", json: { permissions }, retry: false },
  );
  const raw =
    payload && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : {};
  return {
    role: typeof raw.role === "string" ? raw.role : roleName,
    permissions: Array.isArray(raw.permissions)
      ? (raw.permissions as unknown[]).filter(
          (p): p is string => typeof p === "string",
        )
      : permissions,
    overridden_permissions: Array.isArray(raw.overridden_permissions)
      ? (raw.overridden_permissions as unknown[]).filter(
          (p): p is string => typeof p === "string",
        )
      : [],
  };
}

export async function listResourceGrants(params?: {
  resource_type?: string;
  status?: string;
  page?: number;
  page_size?: number;
}): Promise<ResourceAccessListResponse> {
  const qs = new URLSearchParams();
  if (params?.resource_type) qs.set("resource_type", params.resource_type);
  if (params?.status) qs.set("status", params.status);
  if (params?.page) qs.set("page", String(params.page));
  if (params?.page_size) qs.set("page_size", String(params.page_size));
  const url = `${BASE}/resource-grants${qs.size ? `?${qs}` : ""}`;
  const payload = await apiRequest<unknown>(url, {
    method: "GET",
    retry: false,
  });
  const raw =
    payload && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : {};
  return {
    items: Array.isArray(raw.items)
      ? raw.items.map(normalizeResourceAccessEntry)
      : [],
    total: typeof raw.total === "number" ? raw.total : 0,
    page: typeof raw.page === "number" ? raw.page : 1,
    page_size: typeof raw.page_size === "number" ? raw.page_size : 50,
  };
}

export async function createResourceGrant(
  req: CreateResourceAccessRequest,
): Promise<ResourceAccessEntry> {
  const payload = await apiRequest<unknown>(`${BASE}/resource-grants`, {
    method: "POST",
    json: req,
    retry: false,
  });
  return normalizeResourceAccessEntry(payload);
}

export async function revokeResourceGrant(grantId: string): Promise<void> {
  await apiRequest<unknown>(
    `${BASE}/resource-grants/${encodeURIComponent(grantId)}`,
    {
      method: "DELETE",
      retry: false,
    },
  );
}

export async function listResourceDenies(params?: {
  resource_type?: string;
  status?: string;
  page?: number;
  page_size?: number;
}): Promise<ResourceAccessListResponse> {
  const qs = new URLSearchParams();
  if (params?.resource_type) qs.set("resource_type", params.resource_type);
  if (params?.status) qs.set("status", params.status);
  if (params?.page) qs.set("page", String(params.page));
  if (params?.page_size) qs.set("page_size", String(params.page_size));
  const url = `${BASE}/resource-denies${qs.size ? `?${qs}` : ""}`;
  const payload = await apiRequest<unknown>(url, {
    method: "GET",
    retry: false,
  });
  const raw =
    payload && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : {};
  return {
    items: Array.isArray(raw.items)
      ? raw.items.map(normalizeResourceAccessEntry)
      : [],
    total: typeof raw.total === "number" ? raw.total : 0,
    page: typeof raw.page === "number" ? raw.page : 1,
    page_size: typeof raw.page_size === "number" ? raw.page_size : 50,
  };
}

export async function createResourceDeny(
  req: CreateResourceAccessRequest,
): Promise<ResourceAccessEntry> {
  const payload = await apiRequest<unknown>(`${BASE}/resource-denies`, {
    method: "POST",
    json: req,
    retry: false,
  });
  return normalizeResourceAccessEntry(payload);
}

export async function revokeResourceDeny(denyId: string): Promise<void> {
  await apiRequest<unknown>(
    `${BASE}/resource-denies/${encodeURIComponent(denyId)}`,
    {
      method: "DELETE",
      retry: false,
    },
  );
}
