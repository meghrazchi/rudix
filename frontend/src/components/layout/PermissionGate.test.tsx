import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { PermissionGate, AnyPermissionGate } from "@/components/layout/PermissionGate";
import type { UseEffectivePermissionsResult } from "@/lib/use-permissions";

vi.mock("@/lib/use-permissions", () => ({
  useEffectivePermissions: vi.fn(),
}));

import { useEffectivePermissions } from "@/lib/use-permissions";

function mockPermissions(
  permissions: string[],
  isLoading = false,
): UseEffectivePermissionsResult {
  const set = new Set(permissions);
  return {
    role: "member",
    permissions: set,
    isLoading,
    customRoleId: null,
    hasPermission: (p) => set.has(p),
    hasAnyPermission: (...ps) => ps.some((p) => set.has(p)),
    hasAllPermissions: (...ps) => ps.every((p) => set.has(p)),
  };
}

describe("PermissionGate", () => {
  it("renders children when user has the required permission", () => {
    vi.mocked(useEffectivePermissions).mockReturnValue(
      mockPermissions(["documents:view"]),
    );
    render(
      <PermissionGate permissions="documents:view">
        <span>Protected content</span>
      </PermissionGate>,
    );
    expect(screen.getByText("Protected content")).toBeInTheDocument();
  });

  it("hides children when user lacks the required permission", () => {
    vi.mocked(useEffectivePermissions).mockReturnValue(mockPermissions([]));
    render(
      <PermissionGate permissions="documents:delete">
        <span>Delete button</span>
      </PermissionGate>,
    );
    expect(screen.queryByText("Delete button")).not.toBeInTheDocument();
  });

  it("renders fallback when permission denied", () => {
    vi.mocked(useEffectivePermissions).mockReturnValue(mockPermissions([]));
    render(
      <PermissionGate
        permissions="billing:manage"
        fallback={<span>No access</span>}
      >
        <span>Billing panel</span>
      </PermissionGate>,
    );
    expect(screen.queryByText("Billing panel")).not.toBeInTheDocument();
    expect(screen.getByText("No access")).toBeInTheDocument();
  });

  it("renders fallback while loading", () => {
    vi.mocked(useEffectivePermissions).mockReturnValue(
      mockPermissions(["documents:view"], true),
    );
    render(
      <PermissionGate
        permissions="documents:view"
        fallback={<span>Loading...</span>}
      >
        <span>Content</span>
      </PermissionGate>,
    );
    expect(screen.queryByText("Content")).not.toBeInTheDocument();
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("requires ALL permissions when array is given", () => {
    vi.mocked(useEffectivePermissions).mockReturnValue(
      mockPermissions(["documents:view"]),
    );
    render(
      <PermissionGate permissions={["documents:view", "documents:delete"]}>
        <span>Manage documents</span>
      </PermissionGate>,
    );
    expect(screen.queryByText("Manage documents")).not.toBeInTheDocument();
  });

  it("renders when all permissions in array are satisfied", () => {
    vi.mocked(useEffectivePermissions).mockReturnValue(
      mockPermissions(["documents:view", "documents:delete"]),
    );
    render(
      <PermissionGate permissions={["documents:view", "documents:delete"]}>
        <span>Manage documents</span>
      </PermissionGate>,
    );
    expect(screen.getByText("Manage documents")).toBeInTheDocument();
  });
});

describe("AnyPermissionGate", () => {
  it("renders when any permission matches", () => {
    vi.mocked(useEffectivePermissions).mockReturnValue(
      mockPermissions(["chat:use"]),
    );
    render(
      <AnyPermissionGate anyOf={["billing:manage", "chat:use"]}>
        <span>Chat or billing</span>
      </AnyPermissionGate>,
    );
    expect(screen.getByText("Chat or billing")).toBeInTheDocument();
  });

  it("hides when no permission matches", () => {
    vi.mocked(useEffectivePermissions).mockReturnValue(
      mockPermissions(["chat:use"]),
    );
    render(
      <AnyPermissionGate anyOf={["billing:manage", "documents:delete"]}>
        <span>Admin action</span>
      </AnyPermissionGate>,
    );
    expect(screen.queryByText("Admin action")).not.toBeInTheDocument();
  });

  it("renders fallback when denied", () => {
    vi.mocked(useEffectivePermissions).mockReturnValue(mockPermissions([]));
    render(
      <AnyPermissionGate
        anyOf={["billing:manage"]}
        fallback={<span>Upgrade plan</span>}
      >
        <span>Billing</span>
      </AnyPermissionGate>,
    );
    expect(screen.getByText("Upgrade plan")).toBeInTheDocument();
  });
});
