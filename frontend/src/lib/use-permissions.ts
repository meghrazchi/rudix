"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import type { AppRole } from "@/lib/auth-session";
import { useAuthSession } from "@/lib/use-auth-session";
import { fetchEffectivePermissions } from "@/lib/api/auth";
import { queryKeys } from "@/lib/api/query";

// Client-side mirror of the backend ROLE_PERMISSIONS map.
// Keep in sync with backend/app/models/permissions.py
const ROLE_PERMISSIONS: Readonly<Record<AppRole, ReadonlySet<string>>> = {
  viewer: new Set([
    "documents:view",
    "collections:view",
    "chat:use",
    "evaluations:view",
    "agents:use",
    "mcp:use",
    "graph:view",
  ]),
  reviewer: new Set([
    "documents:view",
    "collections:view",
    "chat:use",
    "chat:use_collections",
    "chat:manage_sessions",
    "evaluations:view",
    "evaluations:create",
    "evaluations:run",
    "audit_logs:view",
    "agents:use",
    "mcp:use",
    "graph:view",
  ]),
  developer: new Set([
    "documents:view",
    "documents:upload",
    "collections:view",
    "collections:create",
    "chat:use",
    "chat:use_collections",
    "chat:manage_sessions",
    "evaluations:view",
    "evaluations:create",
    "evaluations:run",
    "api_keys:list",
    "api_keys:create",
    "api_keys:revoke",
    "webhooks:list",
    "webhooks:create",
    "webhooks:delete",
    "agents:use",
    "agents:create",
    "mcp:use",
    "audit_logs:view",
    "graph:view",
  ]),
  member: new Set([
    "documents:view",
    "documents:upload",
    "collections:view",
    "chat:use",
    "chat:use_collections",
    "chat:manage_sessions",
    "evaluations:view",
    "agents:use",
    "mcp:use",
    "graph:view",
  ]),
  billing_admin: new Set([
    "billing:view",
    "billing:manage",
    "audit_logs:view",
    "team:view",
  ]),
  security_admin: new Set([
    "security_center:view",
    "security_center:configure",
    "audit_logs:view",
    "audit_logs:export",
    "team:view",
    "graph:audit_logs:view",
  ]),
  admin: new Set([
    "documents:view",
    "documents:upload",
    "documents:delete",
    "documents:manage",
    "collections:view",
    "collections:create",
    "collections:manage",
    "collections:delete",
    "chat:use",
    "chat:use_collections",
    "chat:manage_sessions",
    "evaluations:view",
    "evaluations:create",
    "evaluations:run",
    "evaluations:manage",
    "audit_logs:view",
    "audit_logs:export",
    "security_center:view",
    "security_center:configure",
    "api_keys:list",
    "api_keys:create",
    "api_keys:revoke",
    "webhooks:list",
    "webhooks:create",
    "webhooks:delete",
    "agents:use",
    "agents:create",
    "agents:manage",
    "mcp:use",
    "mcp:manage",
    "roles:view",
    "roles:manage",
    "team:view",
    "team:manage",
    "graph:view",
    "graph:entities:manage",
    "graph:relations:manage",
    "graph:governance:configure",
    "graph:audit_logs:view",
  ]),
  owner: new Set([
    "documents:view",
    "documents:upload",
    "documents:delete",
    "documents:manage",
    "collections:view",
    "collections:create",
    "collections:manage",
    "collections:delete",
    "chat:use",
    "chat:use_collections",
    "chat:manage_sessions",
    "evaluations:view",
    "evaluations:create",
    "evaluations:run",
    "evaluations:manage",
    "audit_logs:view",
    "audit_logs:export",
    "security_center:view",
    "security_center:configure",
    "billing:view",
    "billing:manage",
    "api_keys:list",
    "api_keys:create",
    "api_keys:revoke",
    "webhooks:list",
    "webhooks:create",
    "webhooks:delete",
    "agents:use",
    "agents:create",
    "agents:manage",
    "mcp:use",
    "mcp:manage",
    "roles:view",
    "roles:manage",
    "team:view",
    "team:manage",
    "graph:view",
    "graph:entities:manage",
    "graph:relations:manage",
    "graph:governance:configure",
    "graph:audit_logs:view",
  ]),
};

export type UsePermissionsResult = {
  role: AppRole | null;
  permissions: ReadonlySet<string>;
  hasPermission: (permission: string) => boolean;
  hasAnyPermission: (...permissions: string[]) => boolean;
  hasAllPermissions: (...permissions: string[]) => boolean;
};

export type UseEffectivePermissionsResult = UsePermissionsResult & {
  isLoading: boolean;
  customRoleId: string | null;
};

// Role-based permissions resolved entirely client-side.
// Use this for synchronous checks where a network round-trip is not acceptable.
export function usePermissions(): UsePermissionsResult {
  const { state } = useAuthSession();
  const role = state.session?.role ?? null;

  const permissions = useMemo<ReadonlySet<string>>(() => {
    if (!role) return new Set();
    return ROLE_PERMISSIONS[role] ?? new Set();
  }, [role]);

  const hasPermission = useMemo(
    () => (permission: string) => permissions.has(permission),
    [permissions],
  );

  const hasAnyPermission = useMemo(
    () =>
      (...perms: string[]) =>
        perms.some((p) => permissions.has(p)),
    [permissions],
  );

  const hasAllPermissions = useMemo(
    () =>
      (...perms: string[]) =>
        perms.every((p) => permissions.has(p)),
    [permissions],
  );

  return {
    role,
    permissions,
    hasPermission,
    hasAnyPermission,
    hasAllPermissions,
  };
}

// Server-fetched effective permissions — supports custom roles.
// Falls back to the role-based map while loading so the UI is never blocked.
export function useEffectivePermissions(): UseEffectivePermissionsResult {
  const { state } = useAuthSession();
  const role = state.session?.role ?? null;
  const isAuthenticated = state.status === "authenticated" && !!state.session;

  const roleBasedPermissions = useMemo<ReadonlySet<string>>(() => {
    if (!role) return new Set();
    return ROLE_PERMISSIONS[role] ?? new Set();
  }, [role]);

  const query = useQuery({
    queryKey: queryKeys.auth.effectivePermissions,
    queryFn: fetchEffectivePermissions,
    enabled: isAuthenticated,
    staleTime: 60_000,
    gcTime: 5 * 60_000,
  });

  const serverPermissions = useMemo<ReadonlySet<string> | null>(() => {
    if (!query.data) return null;
    return new Set(query.data.permissions);
  }, [query.data]);

  // Prefer server permissions once loaded; fall back to role-based while loading.
  const permissions = serverPermissions ?? roleBasedPermissions;

  const hasPermission = useMemo(
    () => (permission: string) => permissions.has(permission),
    [permissions],
  );

  const hasAnyPermission = useMemo(
    () =>
      (...perms: string[]) =>
        perms.some((p) => permissions.has(p)),
    [permissions],
  );

  const hasAllPermissions = useMemo(
    () =>
      (...perms: string[]) =>
        perms.every((p) => permissions.has(p)),
    [permissions],
  );

  return {
    role,
    permissions,
    isLoading: query.isLoading && isAuthenticated,
    customRoleId: query.data?.custom_role_id ?? null,
    hasPermission,
    hasAnyPermission,
    hasAllPermissions,
  };
}
