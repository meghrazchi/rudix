import { describe, expect, it, vi } from "vitest";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";

import { AdminObservabilityPage } from "@/components/admin/AdminObservabilityPage";
import type { SessionState } from "@/lib/auth-session";

const mockState = vi.hoisted(() => ({
  authState: {
    status: "authenticated",
    session: {
      userId: "admin-user",
      email: "admin@example.com",
      role: "admin",
      organizationId: "org-1",
      organizationName: "Test Org",
      accessToken: "token",
    },
  } as SessionState,
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, enabled: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AdminObservabilityPage />
    </QueryClientProvider>,
  );
}

describe("AdminObservabilityPage unit", () => {
  it("renders page heading for admin users", () => {
    renderPage();
    expect(
      screen.getByRole("heading", { name: "Observability" }),
    ).toBeInTheDocument();
  });

  it("renders time range filter buttons", () => {
    renderPage();
    expect(screen.getByRole("button", { name: "7 days" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "14 days" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "30 days" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "90 days" })).toBeInTheDocument();
  });

  it("renders 30d as the initially active range", () => {
    renderPage();
    const btn = screen.getByRole("button", { name: "30 days" });
    expect(btn.className).toContain("bg-[#3525cd]");
  });

  it("renders forbidden state for member role", () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "member-user",
        email: "member@example.com",
        role: "member",
        organizationId: "org-1",
        organizationName: "Test Org",
        accessToken: "token",
      },
    };
    renderPage();
    expect(
      screen.getByText("Admin observability restricted"),
    ).toBeInTheDocument();
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "admin-user",
        email: "admin@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Test Org",
        accessToken: "token",
      },
    };
  });

  it("renders page subtitle", () => {
    renderPage();
    expect(
      screen.getByText(/API health, LLM error rates/i),
    ).toBeInTheDocument();
  });
});
