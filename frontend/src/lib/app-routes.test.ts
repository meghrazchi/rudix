import { describe, expect, it } from "vitest";

import {
  buildNavigationItems,
  findRouteMeta,
  resolveProtectedRouteRedirect,
} from "@/lib/app-routes";
import type { AuthenticatedSession, SessionState } from "@/lib/auth-session";

function authenticatedState(session: AuthenticatedSession): SessionState {
  return { status: "authenticated", session };
}

describe("app route protection", () => {
  it("redirects unauthenticated users to login with next path", () => {
    const state: SessionState = { status: "unauthenticated", session: null };

    expect(resolveProtectedRouteRedirect("/dashboard", state)).toBe("/login?next=%2Fdashboard");
  });

  it("redirects unauthorized users to forbidden page", () => {
    const state = authenticatedState({
      userId: "u-1",
      email: "member@rudix.local",
      role: "member",
      organizationId: "org-1",
      organizationName: "Org 1",
    });

    expect(resolveProtectedRouteRedirect("/admin", state)).toBe("/forbidden?from=%2Fadmin");
  });

  it("matches metadata for all required product pages", () => {
    const expectedPaths = [
      "/dashboard",
      "/documents",
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
});
