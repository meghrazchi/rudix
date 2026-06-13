import { apiRequest } from "@/lib/api/request";

export type PermissionEntry = {
  permission: string;
  category: string;
  description: string;
};

export type PermissionCatalogResponse = {
  items: PermissionEntry[];
  total: number;
};

export type BuiltinRole = {
  role: string;
  label: string;
  description: string;
  permissions: string[];
  is_builtin: true;
};

export type CustomRole = {
  id: string;
  organization_id: string;
  name: string;
  description: string | null;
  base_role: string | null;
  permissions: string[];
  created_by_id: string | null;
  created_at: string;
  updated_at: string;
  is_builtin: false;
};

export type RoleListResponse = {
  builtin_roles: BuiltinRole[];
  custom_roles: CustomRole[];
};

export type CreateCustomRoleRequest = {
  name: string;
  description?: string | null;
  base_role?: string | null;
  permissions: string[];
};

export type UpdateCustomRoleRequest = {
  name?: string | null;
  description?: string | null;
  base_role?: string | null;
  permissions?: string[] | null;
};

const ROLES_BASE = "/admin/roles";

function normalizePermissionEntry(value: unknown): PermissionEntry {
  const raw =
    value && typeof value === "object"
      ? (value as Record<string, unknown>)
      : {};
  return {
    permission: typeof raw.permission === "string" ? raw.permission : "",
    category: typeof raw.category === "string" ? raw.category : "",
    description: typeof raw.description === "string" ? raw.description : "",
  };
}

function normalizeBuiltinRole(value: unknown): BuiltinRole {
  const raw =
    value && typeof value === "object"
      ? (value as Record<string, unknown>)
      : {};
  return {
    role: typeof raw.role === "string" ? raw.role : "",
    label: typeof raw.label === "string" ? raw.label : "",
    description: typeof raw.description === "string" ? raw.description : "",
    permissions: Array.isArray(raw.permissions)
      ? (raw.permissions as unknown[]).filter(
          (p): p is string => typeof p === "string",
        )
      : [],
    is_builtin: true,
  };
}

function normalizeCustomRole(value: unknown): CustomRole {
  const raw =
    value && typeof value === "object"
      ? (value as Record<string, unknown>)
      : {};
  return {
    id: typeof raw.id === "string" ? raw.id : "",
    organization_id:
      typeof raw.organization_id === "string" ? raw.organization_id : "",
    name: typeof raw.name === "string" ? raw.name : "",
    description: typeof raw.description === "string" ? raw.description : null,
    base_role: typeof raw.base_role === "string" ? raw.base_role : null,
    permissions: Array.isArray(raw.permissions)
      ? (raw.permissions as unknown[]).filter(
          (p): p is string => typeof p === "string",
        )
      : [],
    created_by_id:
      typeof raw.created_by_id === "string" ? raw.created_by_id : null,
    created_at: typeof raw.created_at === "string" ? raw.created_at : "",
    updated_at: typeof raw.updated_at === "string" ? raw.updated_at : "",
    is_builtin: false,
  };
}

export async function listPermissions(): Promise<PermissionCatalogResponse> {
  const payload = await apiRequest<unknown>(`${ROLES_BASE}/permissions`, {
    method: "GET",
    retry: false,
  });
  const raw =
    payload && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : {};
  const items = Array.isArray(raw.items)
    ? raw.items.map(normalizePermissionEntry)
    : [];
  return {
    items,
    total: typeof raw.total === "number" ? raw.total : items.length,
  };
}

export async function listRoles(): Promise<RoleListResponse> {
  const payload = await apiRequest<unknown>(ROLES_BASE, {
    method: "GET",
    retry: false,
  });
  const raw =
    payload && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : {};
  return {
    builtin_roles: Array.isArray(raw.builtin_roles)
      ? raw.builtin_roles.map(normalizeBuiltinRole)
      : [],
    custom_roles: Array.isArray(raw.custom_roles)
      ? raw.custom_roles.map(normalizeCustomRole)
      : [],
  };
}

export async function getCustomRole(roleId: string): Promise<CustomRole> {
  const payload = await apiRequest<unknown>(
    `${ROLES_BASE}/${encodeURIComponent(roleId)}`,
    { method: "GET", retry: false },
  );
  return normalizeCustomRole(payload);
}

export async function createCustomRole(
  request: CreateCustomRoleRequest,
): Promise<CustomRole> {
  const payload = await apiRequest<unknown>(ROLES_BASE, {
    method: "POST",
    json: {
      name: request.name,
      description: request.description ?? null,
      base_role: request.base_role ?? null,
      permissions: request.permissions,
    },
    retry: false,
  });
  return normalizeCustomRole(payload);
}

export async function updateCustomRole(
  roleId: string,
  request: UpdateCustomRoleRequest,
): Promise<CustomRole> {
  const payload = await apiRequest<unknown>(
    `${ROLES_BASE}/${encodeURIComponent(roleId)}`,
    { method: "PATCH", json: request, retry: false },
  );
  return normalizeCustomRole(payload);
}

export async function deleteCustomRole(roleId: string): Promise<void> {
  await apiRequest<unknown>(`${ROLES_BASE}/${encodeURIComponent(roleId)}`, {
    method: "DELETE",
    retry: false,
  });
}
