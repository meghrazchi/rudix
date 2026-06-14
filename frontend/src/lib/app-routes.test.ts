import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  buildNavigationItems,
  findRouteMeta,
  resolveAuthenticatedNavigationTarget,
  resolveProtectedRouteRedirect,
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
    expect(adminItem?.hidden).toBe(false);
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
    expect(adminItem?.hidden).toBe(false);
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
