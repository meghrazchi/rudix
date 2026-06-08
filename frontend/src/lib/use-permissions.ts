"use client";

import { useMemo } from "react";

import type { AppRole } from "@/lib/auth-session";
import { useAuthSession } from "@/lib/use-auth-session";

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
  ]),
};

export type UsePermissionsResult = {
  role: AppRole | null;
  permissions: ReadonlySet<string>;
  hasPermission: (permission: string) => boolean;
  hasAnyPermission: (...permissions: string[]) => boolean;
  hasAllPermissions: (...permissions: string[]) => boolean;
};

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
