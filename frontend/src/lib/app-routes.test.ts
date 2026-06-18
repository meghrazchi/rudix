import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  buildNavigationItems,
  evaluateRouteAccess,
  findRouteMeta,
  resolveAuthenticatedNavigationTarget,
  resolveProtectedRouteRedirect,
  APP_ROUTES,
} from "@/lib/app-routes";
import type { AuthenticatedSession, SessionState } from "@/lib/auth-session";

function authenticatedState(session: AuthenticatedSession): SessionState {
  return { status: "authenticated", session };
}

const originalEnv = { ...process.env };

beforeEach(() => {
  process.env = { ...originalEnv };
});

afterEach(() => {
  process.env = { ...originalEnv };
});

describe("app route protection", () => {
  it("redirects app sessions without org id and without token to onboarding", () => {
    process.env = { ...originalEnv, NEXT_PUBLIC_AUTH_PROVIDER: "app" };
    const state = authenticatedState({
      userId: "u-1",
      email: "new@rudix.local",
      role: "member",
      organizationId: null,
      organizationName: null,
      accessToken: null,
    });

    expect(resolveProtectedRouteRedirect("/dashboard", state)).toBe(
      "/organization-onboarding",
    );
  });

  it("redirects unauthenticated users to login with next path", () => {
    const state: SessionState = { status: "unauthenticated", session: null };

    expect(resolveProtectedRouteRedirect("/dashboard", state)).toBe(
      "/login?next=%2Fdashboard",
    );
  });

  it("redirects unauthorized users to forbidden page", () => {
    const state = authenticatedState({
      userId: "u-1",
      email: "member@rudix.local",
      role: "member",
      organizationId: "org-1",
      organizationName: "Org 1",
    });

    expect(resolveProtectedRouteRedirect("/admin", state)).toBe("/forbidden");
    expect(resolveProtectedRouteRedirect("/admin/usage", state)).toBe(
      "/forbidden",
    );
    expect(resolveProtectedRouteRedirect("/admin/audit-logs", state)).toBe(
      "/forbidden",
    );
    expect(resolveProtectedRouteRedirect("/connectors", state)).toBe(
      "/forbidden",
    );
  });

  it("redirects users without organization context to onboarding", () => {
    process.env = { ...originalEnv, NEXT_PUBLIC_AUTH_PROVIDER: "clerk" };
    const state = authenticatedState({
      userId: "u-1",
      email: "new@rudix.local",
      role: "member",
      organizationId: null,
      organizationName: null,
      accessToken: null,
    });

    expect(resolveProtectedRouteRedirect("/dashboard", state)).toBe(
      "/organization-onboarding",
    );
  });

  it("allows app sessions with token even when organization id is missing", () => {
    process.env = { ...originalEnv, NEXT_PUBLIC_AUTH_PROVIDER: "app" };
    const state = authenticatedState({
      userId: "u-1",
      email: "new@rudix.local",
      role: "member",
      organizationId: null,
      organizationName: null,
      accessToken: "token-123",
    });

    expect(resolveProtectedRouteRedirect("/dashboard", state)).toBeNull();
  });

  it("allows app sessions with refresh token even when organization id is missing", () => {
    process.env = { ...originalEnv, NEXT_PUBLIC_AUTH_PROVIDER: "app" };
    const state = authenticatedState({
      userId: "u-1",
      email: "new@rudix.local",
      role: "member",
      organizationId: null,
      organizationName: null,
      accessToken: null,
      refreshToken: "refresh-token-123",
    });

    expect(resolveProtectedRouteRedirect("/dashboard", state)).toBe(
      "/organization-onboarding",
    );
  });

  it("matches metadata for all required product pages", () => {
    const expectedPaths = [
      "/dashboard",
      "/documents",
      "/graph",
      "/chat",
      "/evaluations",
      "/rag-pipeline",
      "/settings",
      "/admin",
    ];

    for (const path of expectedPaths) {
      expect(findRouteMeta(path)).not.toBeNull();
    }
  });
});

describe("permission-aware navigation", () => {
  it("disables admin nav item for member role", () => {
    const nav = buildNavigationItems("/dashboard", {
      userId: "u-1",
      email: "member@rudix.local",
      role: "member",
      organizationId: "org-1",
      organizationName: "Org 1",
    });

    const adminItem = nav.find((item) => item.key === "admin");
    expect(adminItem).toBeDefined();
    expect(adminItem?.disabled).toBe(true);
    expect(adminItem?.hidden).toBe(true);
  });

  it("disables connector nav item for member role", () => {
    const nav = buildNavigationItems("/dashboard", {
      userId: "u-1",
      email: "member@rudix.local",
      role: "member",
      organizationId: "org-1",
      organizationName: "Org 1",
    });

    const connectorsItem = nav.find((item) => item.key === "connectors");
    expect(connectorsItem).toBeDefined();
    expect(connectorsItem?.disabled).toBe(true);
    expect(connectorsItem?.hidden).toBe(false);
  });

  it("allows connector nav item for admin role", () => {
    const nav = buildNavigationItems("/dashboard", {
      userId: "u-2",
      email: "admin@rudix.local",
      role: "admin",
      organizationId: "org-1",
      organizationName: "Org 1",
    });

    const connectorsItem = nav.find((item) => item.key === "connectors");
    expect(connectorsItem).toBeDefined();
    expect(connectorsItem?.disabled).toBe(false);
    expect(connectorsItem?.hidden).toBe(false);
  });

  it("allows admin nav item for admin role", () => {
    const nav = buildNavigationItems("/dashboard", {
      userId: "u-2",
      email: "admin@rudix.local",
      role: "admin",
      organizationId: "org-1",
      organizationName: "Org 1",
    });

    const adminItem = nav.find((item) => item.key === "admin");
    expect(adminItem).toBeDefined();
    expect(adminItem?.disabled).toBe(false);
    expect(adminItem?.hidden).toBe(true);
  });

  it("routes authenticated navigation target to onboarding when organization is missing", () => {
    process.env = { ...originalEnv, NEXT_PUBLIC_AUTH_PROVIDER: "clerk" };
    const target = resolveAuthenticatedNavigationTarget("/dashboard", {
      userId: "u-3",
      email: "member@rudix.local",
      role: "member",
      organizationId: null,
      organizationName: null,
      accessToken: null,
    });

    expect(target).toBe("/organization-onboarding");
  });

  it("keeps authenticated navigation target on requested route for app token sessions", () => {
    process.env = { ...originalEnv, NEXT_PUBLIC_AUTH_PROVIDER: "app" };
    const target = resolveAuthenticatedNavigationTarget("/dashboard", {
      userId: "u-3",
      email: "member@rudix.local",
      role: "member",
      organizationId: null,
      organizationName: null,
      accessToken: "token-xyz",
    });

    expect(target).toBe("/dashboard");
  });
});

describe("permission-based route access", () => {
  const memberSession: AuthenticatedSession = {
    userId: "u-1",
    email: "member@rudix.local",
    role: "member",
    organizationId: "org-1",
    organizationName: "Org 1",
  };

  it("allows access when requiredPermission is satisfied", () => {
    const chatRoute = APP_ROUTES.find((r) => r.key === "chat")!;
    const perms = new Set(["chat:use"]);
    const result = evaluateRouteAccess(chatRoute, memberSession, perms);
    expect(result.allowed).toBe(true);
    expect(result.reason).toBeNull();
  });

  it("denies access with insufficient_permission when requiredPermission is not met", () => {
    const graphRoute = APP_ROUTES.find((r) => r.key === "graph")!;
    const perms = new Set<string>();
    const result = evaluateRouteAccess(graphRoute, memberSession, perms);
    expect(result.allowed).toBe(false);
    expect(result.reason).toBe("insufficient_permission");
  });

  it("does not apply permission check when effectivePermissions arg is omitted", () => {
    const chatRoute = APP_ROUTES.find((r) => r.key === "chat")!;
    const result = evaluateRouteAccess(chatRoute, memberSession);
    expect(result.allowed).toBe(true);
  });

  it("buildNavigationItems disables routes when permission is missing", () => {
    const restrictedPerms = new Set(["chat:use"]);
    const nav = buildNavigationItems("/dashboard", memberSession, restrictedPerms);

    const graphItem = nav.find((item) => item.key === "graph");
    expect(graphItem?.disabled).toBe(true);
    expect(graphItem?.disabledReason).toBe("insufficient_permission");

    const chatItem = nav.find((item) => item.key === "chat");
    expect(chatItem?.disabled).toBe(false);
  });

  it("buildNavigationItems passes all items when all permissions present", () => {
    const fullPerms = new Set([
      "chat:use",
      "documents:view",
      "collections:view",
      "graph:view",
      "evaluations:view",
      "agents:use",
    ]);
    const nav = buildNavigationItems("/dashboard", memberSession, fullPerms);

    const withPermission = nav.filter(
      (item) =>
        item.disabledReason === "insufficient_permission",
    );
    expect(withPermission).toHaveLength(0);
  });

  it("APP_ROUTES document route has requiredPermission documents:view", () => {
    const docsRoute = APP_ROUTES.find((r) => r.key === "documents");
    expect(docsRoute?.requiredPermission).toBe("documents:view");
  });

  it("APP_ROUTES chat route has requiredPermission chat:use", () => {
    const chatRoute = APP_ROUTES.find((r) => r.key === "chat");
    expect(chatRoute?.requiredPermission).toBe("chat:use");
  });

  it("APP_ROUTES graph route has requiredPermission graph:view", () => {
    const graphRoute = APP_ROUTES.find((r) => r.key === "graph");
    expect(graphRoute?.requiredPermission).toBe("graph:view");
  });

  it("connectors route has no requiredPermission (role-gated only)", () => {
    const connectorsRoute = APP_ROUTES.find((r) => r.key === "connectors");
    expect(connectorsRoute?.requiredPermission).toBeUndefined();
  });
});
