import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProviderHealthSection } from "@/components/admin/ProviderHealthSection";
import type {
  ProviderHealthCard,
  ProviderObservabilitySnapshot,
} from "@/lib/api/provider-observability";

const mockApi = vi.hoisted(() => ({
  getProviderObservabilitySnapshot: vi.fn(),
}));

vi.mock("@/lib/api/provider-observability", () => ({
  getProviderObservabilitySnapshot: (query?: unknown) =>
    mockApi.getProviderObservabilitySnapshot(query),
}));

const TIME_RANGE = { from: "2026-05-15", to: "2026-06-13" };

function makeCard(
  overrides: Partial<ProviderHealthCard> = {},
): ProviderHealthCard {
  return {
    provider_key: "openai",
    total_events: 100,
    failed_events: 3,
    failure_rate: 0.03,
    timed_out_events: 1,
    timeout_rate: 0.01,
    fallback_events: 2,
    fallback_rate: 0.02,
    retry_events: 5,
    retry_rate: 0.05,
    avg_retry_count: 1.4,
    avg_latency_ms: 820,
    p95_latency_ms: 2100,
    slo_suggestions: [],
    telemetry_missing: false,
    ...overrides,
  };
}

function makeSnapshot(
  providers: ProviderHealthCard[] = [],
  overrides: Partial<ProviderObservabilitySnapshot> = {},
): ProviderObservabilitySnapshot {
  return {
    organization_id: "org-1",
    range: { from: TIME_RANGE.from, to: TIME_RANGE.to },
    generated_at: "2026-06-13T12:00:00Z",
    providers,
    telemetry_missing: providers.length === 0,
    ...overrides,
  };
}

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("ProviderHealthSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows loading state while data is fetching", async () => {
    mockApi.getProviderObservabilitySnapshot.mockReturnValue(
      new Promise(() => {}),
    );
    render(
      <Wrapper>
        <ProviderHealthSection timeRange={TIME_RANGE} />
      </Wrapper>,
    );
    expect(screen.getByText(/loading provider health/i)).toBeInTheDocument();
  });

  it("shows error state when request fails", async () => {
    mockApi.getProviderObservabilitySnapshot.mockRejectedValue(
      new Error("Network error"),
    );
    render(
      <Wrapper>
        <ProviderHealthSection timeRange={TIME_RANGE} />
      </Wrapper>,
    );
    await waitFor(() => {
      expect(screen.queryByText(/loading/i)).not.toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("shows telemetry_missing notice when no providers", async () => {
    mockApi.getProviderObservabilitySnapshot.mockResolvedValue(
      makeSnapshot([]),
    );
    render(
      <Wrapper>
        <ProviderHealthSection timeRange={TIME_RANGE} />
      </Wrapper>,
    );
    await waitFor(() => {
      expect(
        screen.getByText(/no provider-level telemetry/i),
      ).toBeInTheDocument();
    });
  });

  it("renders provider card with correct key and event count", async () => {
    mockApi.getProviderObservabilitySnapshot.mockResolvedValue(
      makeSnapshot([makeCard({ provider_key: "openai", total_events: 42 })]),
    );
    render(
      <Wrapper>
        <ProviderHealthSection timeRange={TIME_RANGE} />
      </Wrapper>,
    );
    await waitFor(() => {
      expect(screen.getByText("openai")).toBeInTheDocument();
    });
    expect(screen.getByText(/42 events/)).toBeInTheDocument();
  });

  it("renders healthy badge for a low error-rate card", async () => {
    mockApi.getProviderObservabilitySnapshot.mockResolvedValue(
      makeSnapshot([makeCard({ failure_rate: 0.01 })]),
    );
    render(
      <Wrapper>
        <ProviderHealthSection timeRange={TIME_RANGE} />
      </Wrapper>,
    );
    await waitFor(() => {
      expect(screen.getAllByText(/healthy/i).length).toBeGreaterThan(0);
    });
  });

  it("renders degraded badge when failure_rate > 5%", async () => {
    mockApi.getProviderObservabilitySnapshot.mockResolvedValue(
      makeSnapshot([makeCard({ failure_rate: 0.12 })]),
    );
    render(
      <Wrapper>
        <ProviderHealthSection timeRange={TIME_RANGE} />
      </Wrapper>,
    );
    await waitFor(() => {
      expect(screen.getAllByText(/degraded/i).length).toBeGreaterThan(0);
    });
  });

  it("renders multiple provider cards", async () => {
    mockApi.getProviderObservabilitySnapshot.mockResolvedValue(
      makeSnapshot([
        makeCard({ provider_key: "openai" }),
        makeCard({ provider_key: "local", total_events: 20 }),
      ]),
    );
    render(
      <Wrapper>
        <ProviderHealthSection timeRange={TIME_RANGE} />
      </Wrapper>,
    );
    await waitFor(() => {
      expect(screen.getByText("openai")).toBeInTheDocument();
      expect(screen.getByText("local")).toBeInTheDocument();
    });
  });

  it("displays latency metrics in the card", async () => {
    mockApi.getProviderObservabilitySnapshot.mockResolvedValue(
      makeSnapshot([makeCard({ avg_latency_ms: 450, p95_latency_ms: 1200 })]),
    );
    render(
      <Wrapper>
        <ProviderHealthSection timeRange={TIME_RANGE} />
      </Wrapper>,
    );
    await waitFor(() => {
      expect(screen.getByText(/450 ms/)).toBeInTheDocument();
      expect(screen.getByText(/1200 ms/)).toBeInTheDocument();
    });
  });

  it("renders SLO suggestion when present", async () => {
    const cardWithSlo = makeCard({
      failure_rate: 0.12,
      slo_suggestions: [
        {
          metric: "failure_rate",
          current_value: 0.12,
          suggested_threshold: 0.05,
          unit: "ratio",
          rationale: "Too many failures — consider a fallback provider.",
        },
      ],
    });
    mockApi.getProviderObservabilitySnapshot.mockResolvedValue(
      makeSnapshot([cardWithSlo]),
    );
    render(
      <Wrapper>
        <ProviderHealthSection timeRange={TIME_RANGE} />
      </Wrapper>,
    );
    await waitFor(() => {
      expect(screen.getByText(/slo suggestions/i)).toBeInTheDocument();
      expect(screen.getByText(/too many failures/i)).toBeInTheDocument();
    });
  });

  it("does not render SLO section when no suggestions", async () => {
    mockApi.getProviderObservabilitySnapshot.mockResolvedValue(
      makeSnapshot([makeCard({ slo_suggestions: [] })]),
    );
    render(
      <Wrapper>
        <ProviderHealthSection timeRange={TIME_RANGE} />
      </Wrapper>,
    );
    await waitFor(() => {
      expect(screen.getByText("openai")).toBeInTheDocument();
    });
    expect(screen.queryByText(/slo suggestions/i)).not.toBeInTheDocument();
  });

  it("passes date range query to API", async () => {
    mockApi.getProviderObservabilitySnapshot.mockResolvedValue(
      makeSnapshot([]),
    );
    const range = { from: "2026-05-01", to: "2026-05-31" };
    render(
      <Wrapper>
        <ProviderHealthSection timeRange={range} />
      </Wrapper>,
    );
    await waitFor(() => {
      expect(mockApi.getProviderObservabilitySnapshot).toHaveBeenCalledWith(
        range,
      );
    });
  });

  it("shows snapshot timestamp in meta row", async () => {
    mockApi.getProviderObservabilitySnapshot.mockResolvedValue(
      makeSnapshot([makeCard()]),
    );
    render(
      <Wrapper>
        <ProviderHealthSection timeRange={TIME_RANGE} />
      </Wrapper>,
    );
    await waitFor(() => {
      expect(screen.getByText(/provider snapshot at/i)).toBeInTheDocument();
    });
  });

  it("shows 'no data' badge for zero-event provider", async () => {
    mockApi.getProviderObservabilitySnapshot.mockResolvedValue(
      makeSnapshot([
        makeCard({
          total_events: 0,
          failure_rate: null,
          timeout_rate: null,
          fallback_rate: null,
        }),
      ]),
    );
    render(
      <Wrapper>
        <ProviderHealthSection timeRange={TIME_RANGE} />
      </Wrapper>,
    );
    await waitFor(() => {
      expect(screen.getAllByText(/no data/i).length).toBeGreaterThan(0);
    });
  });
});
