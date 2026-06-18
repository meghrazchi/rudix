"use client";

import type { ReactNode } from "react";

import { useEffectivePermissions } from "@/lib/use-permissions";

type PermissionGateProps = {
  // Require ALL listed permissions (AND logic).
  permissions: string | string[];
  // Rendered when access is denied. Default: nothing.
  fallback?: ReactNode;
  children: ReactNode;
};

// Conditionally render children based on the current user's effective permissions.
// Uses server-fetched permissions so custom roles are respected.
// While permissions are loading the fallback is shown (never silently hides content that
// the user actually has access to).
export function PermissionGate({
  permissions,
  fallback = null,
  children,
}: PermissionGateProps) {
  const { hasAllPermissions, isLoading } = useEffectivePermissions();

  const required = Array.isArray(permissions) ? permissions : [permissions];

  if (isLoading) {
    return <>{fallback}</>;
  }

  if (!hasAllPermissions(...required)) {
    return <>{fallback}</>;
  }

  return <>{children}</>;
}

type AnyPermissionGateProps = {
  // Require ANY of the listed permissions (OR logic).
  anyOf: string[];
  fallback?: ReactNode;
  children: ReactNode;
};

// Like PermissionGate but grants access when ANY permission matches.
export function AnyPermissionGate({
  anyOf,
  fallback = null,
  children,
}: AnyPermissionGateProps) {
  const { hasAnyPermission, isLoading } = useEffectivePermissions();

  if (isLoading) {
    return <>{fallback}</>;
  }

  if (!hasAnyPermission(...anyOf)) {
    return <>{fallback}</>;
  }

  return <>{children}</>;
}
