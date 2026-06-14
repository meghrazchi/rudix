import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminGraphObservabilityPage } from "@/components/admin/AdminGraphObservabilityPage";
import type { SessionState } from "@/lib/auth-session";
import type { GraphObservabilitySnapshot } from "@/lib/api/graph-observability";

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  getGraphObservabilitySnapshot: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    session: mockState.authState.session,
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/graph-observability", async (importOriginal) => {
  const original =
    await importOriginal<typeof import("@/lib/api/graph-observability")>();
  return {
    ...original,
    getGraphObservabilitySnapshot: () =>
      mockApi.getGraphObservabilitySnapshot(),
  };
});

function makeAdminSession(): SessionState {
  return {
    status: "authenticated",
    session: {
      userId: "user-1",
      email: "admin@example.com",
      organizationId: "org-1",
      organizationName: "Org 1",
      role: "admin",
    },
  };
}

function makeSnapshot(): GraphObservabilitySnapshot {
  return {
    organization_id: "org-1",
    range: { from: "2026-06-01", to: "2026-06-14" },
    generated_at: "2026-06-14T10:00:00.000Z",
    graph_enabled: true,
    neo4j_reachable: true,
    extraction: {
      total_runs: 4,
      succeeded: 3,
      failed: 1,
      running: 0,
      skipped: 0,
      success_rate: 0.75,
      telemetry_missing: false,
    },
    entities: {
      total_entities: 12,
      by_type: [{ entity_type: "Company", count: 12, avg_confidence: 0.91 }],
      avg_confidence: 0.91,
      low_confidence_count: 1,
      telemetry_missing: false,
    },
    relations: {
      total_relations: 5,
      avg_confidence: 0.88,
      low_confidence_count: 0,
      telemetry_missing: false,
    },
    queries: {
      graphrag_queries: 4,
      graphrag_failures: 1,
      failure_rate: 0.25,
      avg_expansion_size: 5.5,
      avg_latency_ms: 210,
      p95_latency_ms: 300,
      fallback_to_rag: 1,
      fallback_rate: 0.25,
      cypher_failures: 1,
      cypher_failure_rate: 0.25,
      telemetry_missing: false,
    },
    thresholds: {
      extraction_failure_rate_max: 0.2,
      query_failure_rate_max: 0.1,
      graphrag_fallback_rate_max: 0.3,
      low_confidence_entity_rate_max: 0.3,
      query_latency_ms_max: 2000,
    },
    alerts: [
      {
        level: "warning",
        metric: "graphrag_latency_ms_p95",
        message: "GraphRAG p95 latency is 300 ms, exceeding the threshold.",
      },
    ],
    trends: [
      {
        day: "2026-06-13",
        extraction_runs: 2,
        extraction_failure_rate: 0.5,
        graphrag_queries: 2,
        graphrag_failure_rate: 0.5,
        fallback_rate: 0.5,
        avg_latency_ms: 260,
        cypher_failures: 1,
      },
      {
        day: "2026-06-14",
        extraction_runs: 2,
        extraction_failure_rate: 0.0,
        graphrag_queries: 2,
        graphrag_failure_rate: 0.0,
        fallback_rate: 0.0,
        avg_latency_ms: 160,
        cypher_failures: 0,
      },
    ],
  };
}

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

function renderPage() {
  const qc = makeQueryClient();
  render(
    <QueryClientProvider client={qc}>
      <AdminGraphObservabilityPage />
    </QueryClientProvider>,
  );
  return qc;
}

beforeEach(() => {
  vi.clearAllMocks();
  mockState.authState = makeAdminSession();
});

describe("AdminGraphObservabilityPage", () => {
  it("renders graph quality cards and trend rows", async () => {
    mockApi.getGraphObservabilitySnapshot.mockResolvedValue(makeSnapshot());
    renderPage();

    await screen.findByText(/Graph observability/i);

    expect(await screen.findByText("Quality trends")).toBeInTheDocument();
    expect(screen.getByText("GraphRAG queries")).toBeInTheDocument();
    expect(screen.getByText("Neo4j/Cypher failures")).toBeInTheDocument();
    expect(screen.getByText("GraphRAG latency p95 max")).toBeInTheDocument();
    expect(
      screen.getByText(/GraphRAG p95 latency is 300 ms/i),
    ).toBeInTheDocument();
  });

  it("shows forbidden for non-admin users", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u2",
        email: "viewer@example.com",
        organizationId: "org-1",
        organizationName: "Org 1",
        role: "viewer",
      },
    };
    mockApi.getGraphObservabilitySnapshot.mockResolvedValue(makeSnapshot());
    renderPage();

    await waitFor(() =>
      expect(
        screen.getByText(/You do not have permission/i),
      ).toBeInTheDocument(),
    );
  });
});
