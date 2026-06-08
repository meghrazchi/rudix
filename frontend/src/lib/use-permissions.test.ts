import { describe, expect, it, vi } from "vitest";
import { renderHook } from "@testing-library/react";

import { usePermissions } from "@/lib/use-permissions";
import type { SessionState } from "@/lib/auth-session";

function makeSession(role: string): SessionState {
  return {
    status: "authenticated",
    session: {
      userId: "user-1",
      email: "u@example.com",
      role: role as ReturnType<typeof import("@/lib/auth-session").AppRole>,
      organizationId: "org-1",
      organizationName: "Acme",
    },
  };
}

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: vi.fn(),
}));

import { useAuthSession } from "@/lib/use-auth-session";

describe("usePermissions", () => {
  it("owner has billing:manage permission", () => {
    vi.mocked(useAuthSession).mockReturnValue({
      state: makeSession("owner"),
      boundaryEvent: null,
      boundaryMessage: null,
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
      boundaryMessage: null,
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
      boundaryMessage: null,
      setAuthenticatedSession: vi.fn(),
      signOut: vi.fn(),
      clearBoundaryEvent: vi.fn(),
    });
    const { result } = renderHook(() => usePermissions());
    expect(result.current.hasPermission("chat:use")).toBe(true);
    expect(result.current.hasPermission("documents:delete")).toBe(false);
  });

  it("billing_admin has billing:manage and audit_logs:view", () => {
    vi.mocked(useAuthSession).mockReturnValue({
      state: makeSession("billing_admin"),
      boundaryEvent: null,
      boundaryMessage: null,
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
      boundaryMessage: null,
      setAuthenticatedSession: vi.fn(),
      signOut: vi.fn(),
      clearBoundaryEvent: vi.fn(),
    });
    const { result } = renderHook(() => usePermissions());
    expect(result.current.hasPermission("security_center:configure")).toBe(true);
    expect(result.current.hasPermission("billing:manage")).toBe(false);
  });

  it("developer has api_keys:create", () => {
    vi.mocked(useAuthSession).mockReturnValue({
      state: makeSession("developer"),
      boundaryEvent: null,
      boundaryMessage: null,
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
      boundaryMessage: null,
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
      boundaryMessage: null,
      setAuthenticatedSession: vi.fn(),
      signOut: vi.fn(),
      clearBoundaryEvent: vi.fn(),
    });
    const { result } = renderHook(() => usePermissions());
    expect(
      result.current.hasAnyPermission("billing:manage", "chat:use"),
    ).toBe(true);
  });

  it("hasAllPermissions returns false if any missing", () => {
    vi.mocked(useAuthSession).mockReturnValue({
      state: makeSession("viewer"),
      boundaryEvent: null,
      boundaryMessage: null,
      setAuthenticatedSession: vi.fn(),
      signOut: vi.fn(),
      clearBoundaryEvent: vi.fn(),
    });
    const { result } = renderHook(() => usePermissions());
    expect(
      result.current.hasAllPermissions("chat:use", "billing:manage"),
    ).toBe(false);
  });

  it("null role returns empty permissions", () => {
    vi.mocked(useAuthSession).mockReturnValue({
      state: { status: "unauthenticated", session: null },
      boundaryEvent: null,
      boundaryMessage: null,
      setAuthenticatedSession: vi.fn(),
      signOut: vi.fn(),
      clearBoundaryEvent: vi.fn(),
    });
    const { result } = renderHook(() => usePermissions());
    expect(result.current.permissions.size).toBe(0);
    expect(result.current.hasPermission("chat:use")).toBe(false);
  });
});
