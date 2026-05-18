import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { AdminSystemHealthPage } from "@/components/admin/AdminSystemHealthPage";
import type { SessionState } from "@/lib/auth-session";
import type { HealthResponse } from "@/lib/api/health";

const apiBaseUrl = "http://api.test";

const mockState = vi.hoisted(() => ({
  authState: { status: "authenticated", session: null } as SessionState,
}));

let healthRequestCount = 0;
let readinessRequestCount = 0;
let healthResponse: HealthResponse;
let readinessResponse: HealthResponse;

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

function buildHealthyResponse(): HealthResponse {
  return {
    status: "ok",
    timestamp: "2026-05-18T10:00:00Z",
    dependencies: {
      postgresql: { ok: true, detail: "Connected", metadata: { latency_ms: 10 } },
      redis: { ok: true, detail: "Connected", metadata: { latency_ms: 4 } },
      rabbitmq: { ok: true, detail: "Connected", metadata: { latency_ms: 6 } },
      minio: { ok: true, detail: "Connected", metadata: { latency_ms: 9 } },
      qdrant: { ok: true, detail: "Connected", metadata: { latency_ms: 14 } },
      openai: { ok: true, detail: "Configured", metadata: { configured: true } },
    },
    failed_dependencies: [],
  };
}

const server = setupServer(
  http.get(`${apiBaseUrl}/health`, () => {
    healthRequestCount += 1;
    return HttpResponse.json(healthResponse);
  }),
  http.get(`${apiBaseUrl}/ready`, () => {
    readinessRequestCount += 1;
    return HttpResponse.json(readinessResponse);
  }),
);

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <AdminSystemHealthPage />
    </QueryClientProvider>,
  );
}

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  server.resetHandlers();
  healthRequestCount = 0;
  readinessRequestCount = 0;
});

afterAll(() => {
  server.close();
});

beforeEach(() => {
  process.env.NEXT_PUBLIC_API_URL = apiBaseUrl;
  process.env.NEXT_PUBLIC_ADMIN_HEALTH_REFRESH_INTERVAL_MS = "";

  healthResponse = buildHealthyResponse();
  readinessResponse = buildHealthyResponse();

  mockState.authState = {
    status: "authenticated",
    session: {
      userId: "admin-user",
      email: "admin@example.com",
      role: "admin",
      organizationId: "org-1",
      organizationName: "Org One",
      accessToken: "access-token",
    },
  };
});

describe("AdminSystemHealthPage MSW", () => {
  it("renders healthy health/readiness checks for admin users", async () => {
    renderPage();

    await screen.findByRole("heading", { name: "System health" });
    await screen.findByText("API Health (/health)");
    await screen.findByText("Readiness (/ready)");
    await waitFor(() => {
      expect(screen.getAllByText("All reported dependencies are healthy.")).toHaveLength(2);
    });
    expect(screen.getAllByText("PostgreSQL").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("OpenAI Config").length).toBeGreaterThanOrEqual(1);
    expect(healthRequestCount).toBe(1);
    expect(readinessRequestCount).toBe(1);
  });

  it("renders degraded readiness with failed dependency details", async () => {
    readinessResponse = {
      ...buildHealthyResponse(),
      status: "degraded",
      dependencies: {
        ...buildHealthyResponse().dependencies,
        redis: { ok: false, detail: "Connection refused", metadata: { retry_in_seconds: 5 } },
        qdrant: { ok: false, detail: "Collection unavailable", metadata: { collection: "documents" } },
      },
      failed_dependencies: ["redis", "qdrant"],
    };

    renderPage();

    expect(await screen.findByText("Readiness (/ready)")).toBeInTheDocument();
    expect(await screen.findByText(/failed dependencies:/i)).toBeInTheDocument();
    expect(await screen.findByText(/redis, qdrant/i)).toBeInTheDocument();
    expect(await screen.findByText("Connection refused")).toBeInTheDocument();
    expect(await screen.findByText("Collection unavailable")).toBeInTheDocument();
  });

  it("refreshes health checks when refresh button is clicked", async () => {
    renderPage();
    await screen.findByText("API Health (/health)");
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Refresh checks" })).toBeEnabled();
    });

    expect(healthRequestCount).toBe(1);
    expect(readinessRequestCount).toBe(1);

    await userEvent.click(screen.getByRole("button", { name: "Refresh checks" }));

    await waitFor(() => {
      expect(healthRequestCount).toBe(2);
      expect(readinessRequestCount).toBe(2);
    });
  });

  it("shows forbidden state and skips health queries for non-admin users", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "member-user",
        email: "member@example.com",
        role: "member",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "member-token",
      },
    };

    renderPage();

    expect(await screen.findByText("Admin health restricted")).toBeInTheDocument();
    expect(healthRequestCount).toBe(0);
    expect(readinessRequestCount).toBe(0);
  });
});
