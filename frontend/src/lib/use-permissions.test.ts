import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { createElement } from "react";

import { usePermissions, useEffectivePermissions } from "@/lib/use-permissions";
import type { SessionState } from "@/lib/auth-session";
import {
  writeSessionToStorage,
  clearSessionStorage,
} from "@/lib/auth-session";

function makeSession(role: string): SessionState {
  return {
    status: "authenticated",
    session: {
      userId: "user-1",
      email: "u@example.com",
      role: role as import("@/lib/auth-session").AppRole,
      organizationId: "org-1",
      organizationName: "Acme",
    },
  };
}

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: vi.fn(),
}));

vi.mock("@/lib/api/auth", () => ({
  fetchEffectivePermissions: vi.fn(),
}));

import { useAuthSession } from "@/lib/use-auth-session";
import { fetchEffectivePermissions } from "@/lib/api/auth";

function makeQueryWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client: queryClient }, children);
  }
  return { Wrapper, queryClient };
}

describe("usePermissions", () => {
  it("owner has billing:manage permission", () => {
    vi.mocked(useAuthSession).mockReturnValue({
      state: makeSession("owner"),
      boundaryEvent: null,
      boundaryMessageKey: null,
      setAuthenticatedSession: vi.fn(),
      signOut: vi.fn(),
      clearBoundaryEvent: vi.fn(),
    });
    const { result } = renderHook(() => usePermissions());
    expect(result.current.hasPermission("billing:manage")).toBe(true);
  });

  it("admin does not have billing:manage", () => {
    vi.mocked(useAuthSession).mockReturnValue({
      state: makeSession("admin"),
      boundaryEvent: null,
      boundaryMessageKey: null,
      setAuthenticatedSession: vi.fn(),
      signOut: vi.fn(),
      clearBoundaryEvent: vi.fn(),
    });
    const { result } = renderHook(() => usePermissions());
    expect(result.current.hasPermission("billing:manage")).toBe(false);
  });

  it("viewer has chat:use but not documents:delete", () => {
    vi.mocked(useAuthSession).mockReturnValue({
      state: makeSession("viewer"),
      boundaryEvent: null,
      boundaryMessageKey: null,
      setAuthenticatedSession: vi.fn(),
      signOut: vi.fn(),
      clearBoundaryEvent: vi.fn(),
    });
    const { result } = renderHook(() => usePermissions());
    expect(result.current.hasPermission("chat:use")).toBe(true);
    expect(result.current.hasPermission("documents:delete")).toBe(false);
  });

  it("viewer has graph:view", () => {
    vi.mocked(useAuthSession).mockReturnValue({
      state: makeSession("viewer"),
      boundaryEvent: null,
      boundaryMessageKey: null,
      setAuthenticatedSession: vi.fn(),
      signOut: vi.fn(),
      clearBoundaryEvent: vi.fn(),
    });
    const { result } = renderHook(() => usePermissions());
    expect(result.current.hasPermission("graph:view")).toBe(true);
  });

  it("billing_admin has billing:manage and audit_logs:view", () => {
    vi.mocked(useAuthSession).mockReturnValue({
      state: makeSession("billing_admin"),
      boundaryEvent: null,
      boundaryMessageKey: null,
      setAuthenticatedSession: vi.fn(),
      signOut: vi.fn(),
      clearBoundaryEvent: vi.fn(),
    });
    const { result } = renderHook(() => usePermissions());
    expect(result.current.hasPermission("billing:manage")).toBe(true);
    expect(result.current.hasPermission("audit_logs:view")).toBe(true);
    expect(result.current.hasPermission("documents:view")).toBe(false);
  });

  it("security_admin can configure security but not billing", () => {
    vi.mocked(useAuthSession).mockReturnValue({
      state: makeSession("security_admin"),
      boundaryEvent: null,
      boundaryMessageKey: null,
      setAuthenticatedSession: vi.fn(),
      signOut: vi.fn(),
      clearBoundaryEvent: vi.fn(),
    });
    const { result } = renderHook(() => usePermissions());
    expect(result.current.hasPermission("security_center:configure")).toBe(
      true,
    );
    expect(result.current.hasPermission("billing:manage")).toBe(false);
  });

  it("developer has api_keys:create", () => {
    vi.mocked(useAuthSession).mockReturnValue({
      state: makeSession("developer"),
      boundaryEvent: null,
      boundaryMessageKey: null,
      setAuthenticatedSession: vi.fn(),
      signOut: vi.fn(),
      clearBoundaryEvent: vi.fn(),
    });
    const { result } = renderHook(() => usePermissions());
    expect(result.current.hasPermission("api_keys:create")).toBe(true);
    expect(result.current.hasPermission("billing:view")).toBe(false);
  });

  it("reviewer has evaluations:run and audit_logs:view", () => {
    vi.mocked(useAuthSession).mockReturnValue({
      state: makeSession("reviewer"),
      boundaryEvent: null,
      boundaryMessageKey: null,
      setAuthenticatedSession: vi.fn(),
      signOut: vi.fn(),
      clearBoundaryEvent: vi.fn(),
    });
    const { result } = renderHook(() => usePermissions());
    expect(result.current.hasPermission("evaluations:run")).toBe(true);
    expect(result.current.hasPermission("audit_logs:view")).toBe(true);
  });

  it("hasAnyPermission returns true when any match", () => {
    vi.mocked(useAuthSession).mockReturnValue({
      state: makeSession("viewer"),
      boundaryEvent: null,
      boundaryMessageKey: null,
      setAuthenticatedSession: vi.fn(),
      signOut: vi.fn(),
      clearBoundaryEvent: vi.fn(),
    });
    const { result } = renderHook(() => usePermissions());
    expect(result.current.hasAnyPermission("billing:manage", "chat:use")).toBe(
      true,
    );
  });

  it("hasAllPermissions returns false if any missing", () => {
    vi.mocked(useAuthSession).mockReturnValue({
      state: makeSession("viewer"),
      boundaryEvent: null,
      boundaryMessageKey: null,
      setAuthenticatedSession: vi.fn(),
      signOut: vi.fn(),
      clearBoundaryEvent: vi.fn(),
    });
    const { result } = renderHook(() => usePermissions());
    expect(result.current.hasAllPermissions("chat:use", "billing:manage")).toBe(
      false,
    );
  });

  it("null role returns empty permissions", () => {
    vi.mocked(useAuthSession).mockReturnValue({
      state: { status: "unauthenticated", session: null },
      boundaryEvent: null,
      boundaryMessageKey: null,
      setAuthenticatedSession: vi.fn(),
      signOut: vi.fn(),
      clearBoundaryEvent: vi.fn(),
    });
    const { result } = renderHook(() => usePermissions());
    expect(result.current.permissions.size).toBe(0);
    expect(result.current.hasPermission("chat:use")).toBe(false);
  });
});

describe("useEffectivePermissions", () => {
  beforeEach(() => {
    vi.mocked(fetchEffectivePermissions).mockReset();
  });

  it("falls back to role-based permissions while server response is loading", () => {
    vi.mocked(useAuthSession).mockReturnValue({
      state: makeSession("viewer"),
      boundaryEvent: null,
      boundaryMessageKey: null,
      setAuthenticatedSession: vi.fn(),
      signOut: vi.fn(),
      clearBoundaryEvent: vi.fn(),
    });
    vi.mocked(fetchEffectivePermissions).mockReturnValue(new Promise(() => {}));

    const { Wrapper } = makeQueryWrapper();
    const { result } = renderHook(() => useEffectivePermissions(), {
      wrapper: Wrapper,
    });

    expect(result.current.isLoading).toBe(true);
    expect(result.current.hasPermission("chat:use")).toBe(true);
    expect(result.current.hasPermission("billing:manage")).toBe(false);
  });

  it("uses server permissions once loaded", async () => {
    vi.mocked(useAuthSession).mockReturnValue({
      state: makeSession("viewer"),
      boundaryEvent: null,
      boundaryMessageKey: null,
      setAuthenticatedSession: vi.fn(),
      signOut: vi.fn(),
      clearBoundaryEvent: vi.fn(),
    });
    vi.mocked(fetchEffectivePermissions).mockResolvedValue({
      permissions: ["chat:use", "documents:upload", "custom:extra"],
      role: "viewer",
      custom_role_id: "custom-role-123",
    });

    const { Wrapper } = makeQueryWrapper();
    const { result } = renderHook(() => useEffectivePermissions(), {
      wrapper: Wrapper,
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.hasPermission("chat:use")).toBe(true);
    expect(result.current.hasPermission("documents:upload")).toBe(true);
    expect(result.current.hasPermission("custom:extra")).toBe(true);
    expect(result.current.hasPermission("billing:manage")).toBe(false);
    expect(result.current.customRoleId).toBe("custom-role-123");
  });

  it("server permissions override role-based map (custom role removes permissions)", async () => {
    vi.mocked(useAuthSession).mockReturnValue({
      state: makeSession("admin"),
      boundaryEvent: null,
      boundaryMessageKey: null,
      setAuthenticatedSession: vi.fn(),
      signOut: vi.fn(),
      clearBoundaryEvent: vi.fn(),
    });
    vi.mocked(fetchEffectivePermissions).mockResolvedValue({
      permissions: ["documents:view"],
      role: "admin",
      custom_role_id: "restricted-admin",
    });

    const { Wrapper } = makeQueryWrapper();
    const { result } = renderHook(() => useEffectivePermissions(), {
      wrapper: Wrapper,
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.hasPermission("documents:view")).toBe(true);
    expect(result.current.hasPermission("documents:delete")).toBe(false);
    expect(result.current.hasPermission("billing:manage")).toBe(false);
  });

  it("does not fetch when unauthenticated", () => {
    vi.mocked(useAuthSession).mockReturnValue({
      state: { status: "unauthenticated", session: null },
      boundaryEvent: null,
      boundaryMessageKey: null,
      setAuthenticatedSession: vi.fn(),
      signOut: vi.fn(),
      clearBoundaryEvent: vi.fn(),
    });

    const { Wrapper } = makeQueryWrapper();
    renderHook(() => useEffectivePermissions(), { wrapper: Wrapper });

    expect(fetchEffectivePermissions).not.toHaveBeenCalled();
  });

  it("customRoleId is null when user has no custom role", async () => {
    vi.mocked(useAuthSession).mockReturnValue({
      state: makeSession("owner"),
      boundaryEvent: null,
      boundaryMessageKey: null,
      setAuthenticatedSession: vi.fn(),
      signOut: vi.fn(),
      clearBoundaryEvent: vi.fn(),
    });
    vi.mocked(fetchEffectivePermissions).mockResolvedValue({
      permissions: ["billing:manage", "documents:view"],
      role: "owner",
      custom_role_id: null,
    });

    const { Wrapper } = makeQueryWrapper();
    const { result } = renderHook(() => useEffectivePermissions(), {
      wrapper: Wrapper,
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.customRoleId).toBeNull();
  });
});
