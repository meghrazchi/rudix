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

    expect(screen.getByText(/Admin [Ll]anding/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open Usage/i })).toHaveAttribute(
      "href",
      "/admin/usage",
    );
    expect(screen.getByRole("link", { name: /Open Logs/i })).toHaveAttribute(
      "href",
      "/admin/audit-logs",
    );
    expect(
      screen.getByRole("link", { name: /Open Security/i }),
    ).toHaveAttribute("href", "/admin/security-center");
    expect(screen.getByRole("link", { name: /Open Health/i })).toHaveAttribute(
      "href",
      "/admin/system-health",
    );
    expect(
      screen.getByRole("link", { name: /Manage Policies/i }),
    ).toHaveAttribute("href", "/admin/governance");
    expect(screen.getAllByText(/unavailable/i).length).toBeGreaterThan(0);
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
    expect(
      screen.queryByText("Unavailable in this deployment"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Open Monitoring" }),
    ).toHaveAttribute("href", "/admin/monitoring");
  });
});
