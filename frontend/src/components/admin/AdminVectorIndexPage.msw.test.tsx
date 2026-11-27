import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { AdminVectorIndexPage } from "@/components/admin/AdminVectorIndexPage";
import { getVectorIndexStatus } from "@/lib/api/vector-index";
import type { SessionState } from "@/lib/auth-session";

const apiBaseUrl = "http://api.test";

const mockState = vi.hoisted(() => ({
  authState: { status: "authenticated", session: null } as SessionState,
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

let statusRequests = 0;

const STATUS = {
  alias: "rudix_live",
  legacy_mode: false,
  active: {
    generation: 1,
    embedding_model: "text-embedding-3-small",
    vector_size: 1536,
    activated_at: "2026-11-01T00:00:00Z",
  },
  building: {
    generation: 2,
    embedding_model: "text-embedding-3-large",
    state: "verifying",
    started_at: "2026-11-27T10:00:00Z",
  },
  progress: { documents_total: 4, documents_done: 4 },
};

const server = setupServer(
  http.get(`${apiBaseUrl}/admin/vector-index/status`, () => {
    statusRequests += 1;
    return HttpResponse.json(STATUS);
  }),
);

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AdminVectorIndexPage />
    </QueryClientProvider>,
  );
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  statusRequests = 0;
});
afterAll(() => server.close());

beforeEach(() => {
  process.env.NEXT_PUBLIC_API_URL = apiBaseUrl;
  mockState.authState = {
    status: "authenticated",
    session: {
      userId: "owner-user",
      email: "owner@example.com",
      role: "owner",
      organizationId: "org-1",
      organizationName: "Org One",
      accessToken: "access-token",
    },
  };
});

describe("AdminVectorIndexPage MSW", () => {
  it("loads the status over the network", async () => {
    renderPage();

    await screen.findByText("text-embedding-3-large");
    expect(screen.getByText("Verifying")).toBeInTheDocument();
    expect(screen.getByText("4 of 4 (100%)")).toBeInTheDocument();
    expect(statusRequests).toBe(1);
  });

  it("rejects a payload that does not match the contract", async () => {
    server.use(
      http.get(`${apiBaseUrl}/admin/vector-index/status`, () =>
        HttpResponse.json({ alias: 1 }),
      ),
    );
    await expect(getVectorIndexStatus()).rejects.toThrow();
  });

  it("shows the server's request id on a failure", async () => {
    server.use(
      http.get(`${apiBaseUrl}/admin/vector-index/status`, () =>
        HttpResponse.json(
          { error: { code: "internal_error", message: "boom" } },
          { status: 500, headers: { "X-Request-ID": "req-vi-500" } },
        ),
      ),
    );
    renderPage();

    await screen.findByText("Unable to load the vector index status");
    expect(screen.getByText("req-vi-500")).toBeInTheDocument();
  });
});
