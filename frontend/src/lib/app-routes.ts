import type {
  AppRole,
  AuthenticatedSession,
  SessionState,
} from "@/lib/auth-session";
import { getFrontendRuntimeConfig } from "@/lib/runtime-config";

export type AppRouteKey =
  | "dashboard"
  | "documents"
  | "collections"
  | "chat"
  | "evaluations"
  | "pipeline"
  | "connectors"
  | "settings"
  | "admin";

export type AppRouteMeta = {
  key: AppRouteKey;
  href: string;
  label: string;
  description: string;
  matchPrefixes: string[];
  requiresOrganization: boolean;
  allowedRoles: AppRole[];
};

export type RouteAccessReason =
  | "unauthenticated"
  | "organization_required"
  | "insufficient_role"
  | null;

export type RouteAccess = {
  allowed: boolean;
  reason: RouteAccessReason;
};

export type AppNavigationItem = AppRouteMeta & {
  isActive: boolean;
  hidden: boolean;
  disabled: boolean;
  disabledReason: Exclude<RouteAccessReason, null> | null;
};

export const APP_ROUTES: AppRouteMeta[] = [
  {
    key: "dashboard",
    href: "/dashboard",
    label: "Dashboard",
    description: "Overview and system performance",
    matchPrefixes: ["/dashboard"],
    requiresOrganization: true,
    allowedRoles: ["owner", "admin", "member", "viewer"],
  },
  {
    key: "documents",
    href: "/documents",
    label: "Documents",
    description: "Manage and monitor uploaded documents",
    matchPrefixes: ["/documents"],
    requiresOrganization: true,
    allowedRoles: ["owner", "admin", "member", "viewer"],
  },
  {
    key: "collections",
    href: "/collections",
    label: "Collections",
    description: "Organize documents into knowledge bases by topic or team",
    matchPrefixes: ["/collections"],
    requiresOrganization: true,
    allowedRoles: ["owner", "admin", "member", "viewer"],
  },
  {
    key: "chat",
    href: "/chat",
    label: "Chat",
    description: "Ask questions against indexed documents",
    matchPrefixes: ["/chat"],
    requiresOrganization: true,
    allowedRoles: ["owner", "admin", "member", "viewer"],
  },
  {
    key: "evaluations",
    href: "/evaluations",
    label: "Evaluations",
    description: "Track and compare evaluation runs",
    matchPrefixes: ["/evaluations"],
    requiresOrganization: true,
    allowedRoles: ["owner", "admin", "member", "viewer"],
  },
  {
    key: "pipeline",
    href: "/rag-pipeline",
    label: "Pipeline Explorer",
    description: "Inspect processing and query pipeline internals",
    matchPrefixes: ["/rag-pipeline", "/pipeline-explorer"],
    requiresOrganization: true,
    allowedRoles: ["owner", "admin", "member", "viewer"],
  },
  {
    key: "connectors",
    href: "/connectors",
    label: "Connectors",
    description: "Connect external sources like Jira, Confluence, and Google Drive",
    matchPrefixes: ["/connectors"],
    requiresOrganization: true,
    allowedRoles: ["owner", "admin", "member", "viewer"],
  },
  {
    key: "settings",
    href: "/settings",
    label: "Settings",
    description: "Organization and account settings",
    matchPrefixes: ["/settings"],
    requiresOrganization: true,
    allowedRoles: ["owner", "admin", "member", "viewer"],
  },
  {
    key: "admin",
    href: "/admin",
    label: "Admin",
    description: "Administrative analytics and controls",
    matchPrefixes: ["/admin"],
    requiresOrganization: true,
    allowedRoles: ["owner", "admin"],
  },
];

function normalizePathname(pathname: string): string {
  if (!pathname) {
    return "/";
  }
  const withoutQuery = pathname.split("?")[0] ?? pathname;
  return withoutQuery.replace(/\/+$/, "") || "/";
}

function hasOrganizationContext(session: AuthenticatedSession): boolean {
  if (session.organizationId?.trim()) {
    return true;
  }

  const provider = getFrontendRuntimeConfig().authProvider;
  if (
    provider === "app" &&
    (session.accessToken?.trim() || session.refreshToken?.trim())
  ) {
    // App auth can resolve the active organization server-side from token principal memberships.
    return true;
  }

  return false;
}

export function findRouteMeta(pathname: string): AppRouteMeta | null {
  const normalizedPathname = normalizePathname(pathname);
  return (
    APP_ROUTES.find((route) =>
      route.matchPrefixes.some(
        (prefix) =>
          normalizedPathname === prefix ||
          normalizedPathname.startsWith(`${prefix}/`),
      ),
    ) ?? null
  );
}

export function evaluateRouteAccess(
  route: AppRouteMeta,
  session: AuthenticatedSession | null,
): RouteAccess {
  if (!session) {
    return { allowed: false, reason: "unauthenticated" };
  }
  if (route.requiresOrganization && !hasOrganizationContext(session)) {
    return { allowed: false, reason: "organization_required" };
  }
  if (!route.allowedRoles.includes(session.role)) {
    return { allowed: false, reason: "insufficient_role" };
  }
  return { allowed: true, reason: null };
}

export function buildNavigationItems(
  pathname: string,
  session: AuthenticatedSession | null,
): AppNavigationItem[] {
  const normalizedPathname = normalizePathname(pathname);

  return APP_ROUTES.map((route) => {
    const access = evaluateRouteAccess(route, session);
    const isMissingOrganization = access.reason === "organization_required";
    return {
      ...route,
      isActive: route.matchPrefixes.some(
        (prefix) =>
          normalizedPathname === prefix ||
          normalizedPathname.startsWith(`${prefix}/`),
      ),
      hidden: isMissingOrganization,
      disabled: !access.allowed && !isMissingOrganization,
      disabledReason:
        access.allowed || isMissingOrganization ? null : access.reason,
    };
  });
}

export function resolveProtectedRouteRedirect(
  pathname: string,
  state: SessionState,
): string | null {
  const route = findRouteMeta(pathname);
  if (!route) {
    return null;
  }

  if (state.status === "loading") {
    return null;
  }

  const access = evaluateRouteAccess(route, state.session);
  if (access.allowed) {
    return null;
  }

  if (access.reason === "unauthenticated") {
    const encodedPath = encodeURIComponent(normalizePathname(pathname));
    return `/login?next=${encodedPath}`;
  }
  if (access.reason === "organization_required") {
    return "/organization-onboarding";
  }
  return "/forbidden";
}

export function resolveAuthenticatedNavigationTarget(
  pathname: string,
  session: AuthenticatedSession,
): string {
  const normalizedPath = normalizePathname(pathname);
  const route = findRouteMeta(normalizedPath);
  if (!route) {
    return normalizedPath;
  }

  const access = evaluateRouteAccess(route, session);
  if (access.allowed) {
    return normalizedPath;
  }

  if (access.reason === "organization_required") {
    return "/organization-onboarding";
  }

  if (access.reason === "insufficient_role") {
    return "/forbidden";
  }

  const encodedPath = encodeURIComponent(normalizedPath);
  return `/login?next=${encodedPath}`;
}
