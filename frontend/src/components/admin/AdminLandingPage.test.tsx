import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdminLandingPage } from "@/components/admin/AdminLandingPage";
import type { SessionState } from "@/lib/auth-session";

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

const originalEnv = { ...process.env };

describe("AdminLandingPage", () => {
  beforeEach(() => {
    process.env = { ...originalEnv };
  });

  afterEach(() => {
    process.env = { ...originalEnv };
  });

  it("renders admin cards and internal links for admin role", () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-1",
        email: "admin@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Org 1",
        accessToken: "token-1",
      },
    };

    render(<AdminLandingPage />);

    expect(screen.getByText("Admin landing")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Usage analytics" })).toHaveAttribute("href", "/admin/usage");
    expect(screen.getByRole("link", { name: "Open Audit logs" })).toHaveAttribute("href", "/admin/audit");
    expect(screen.getByRole("link", { name: "Open System health" })).toHaveAttribute("href", "/admin/system-health");
    expect(screen.getByText("Unavailable in this deployment")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View setup details" })).toHaveAttribute("href", "/admin/monitoring");
  });

  it("renders forbidden state for non-admin role", () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-2",
        email: "member@example.com",
        role: "member",
        organizationId: "org-1",
        organizationName: "Org 1",
        accessToken: "token-2",
      },
    };

    render(<AdminLandingPage />);
    expect(screen.getByText("Admin area restricted")).toBeInTheDocument();
  });

  it("uses configured monitoring URL when available", () => {
    process.env = {
      ...originalEnv,
      NEXT_PUBLIC_ADMIN_MONITORING_URL: "https://monitoring.example.com/rudix",
    };

    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-3",
        email: "owner@example.com",
        role: "owner",
        organizationId: "org-1",
        organizationName: "Org 1",
        accessToken: "token-3",
      },
    };

    render(<AdminLandingPage />);
    expect(screen.queryByText("Unavailable in this deployment")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Monitoring" })).toHaveAttribute(
      "href",
      "https://monitoring.example.com/rudix",
    );
  });
});
