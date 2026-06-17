import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentTraceReplayPage } from "@/components/workspace/AgentTraceReplayPage";
import type {
  AgentTraceExportResponse,
  AgentTraceResponse,
  AgentTraceShareResponse,
} from "@/lib/api/agent";

// ── Mock: agent API ───────────────────────────────────────────────────────────

const mockApi = vi.hoisted(() => ({
  getAgentRunTrace: vi.fn(),
  exportAgentRunTrace: vi.fn(),
  shareAgentRunTrace: vi.fn(),
}));

vi.mock("@/lib/api/agent", () => ({
  getAgentRunTrace: (...args: unknown[]) => mockApi.getAgentRunTrace(...args),
  exportAgentRunTrace: (...args: unknown[]) =>
    mockApi.exportAgentRunTrace(...args),
  shareAgentRunTrace: (...args: unknown[]) =>
    mockApi.shareAgentRunTrace(...args),
}));

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
  }: {
    children: React.ReactNode;
    href: string;
  }) => <a href={href}>{children}</a>,
}));

// ── Helpers ────────────────────────────────────────────────────────────────────

const NOW = "2026-06-20T10:00:00.000Z";
const RUN_ID = "run-f174-abc1";

function makeTrace(
  overrides: Partial<AgentTraceResponse> = {},
): AgentTraceResponse {
  return {
    run_id: RUN_ID,
    organization_id: "org-1",
    status: "completed",
    objective: "Summarise quarterly results",
    surface: "api",
    started_at: NOW,
    completed_at: NOW,
    cancelled_at: null,
    created_at: NOW,
    total_cost_usd: "0.001234",
    error_message: null,
    trace_request_id: "trace-xyz",
    redacted: false,
    timeline: [
      {
        event_type: "run_started",
        run_id: RUN_ID,
        timestamp: NOW,
        data: { objective: "Summarise quarterly results", status: "running" },
      },
      {
        event_type: "step_started",
        run_id: RUN_ID,
        step_id: "step-1",
        timestamp: NOW,
        data: { sequence: 0, step_name: "retrieve_documents", inputs: {} },
      },
      {
        event_type: "tool_called",
        run_id: RUN_ID,
        step_id: "step-1",
        tool_call_id: "tc-1",
        timestamp: NOW,
        data: {
          tool_name: "search_documents",
          surface: "api",
          effect_policy: "read_only",
          attempt_number: 1,
          arguments: { query: "quarterly results" },
        },
      },
      {
        event_type: "tool_result",
        run_id: RUN_ID,
        step_id: "step-1",
        tool_call_id: "tc-1",
        timestamp: NOW,
        data: {
          tool_name: "search_documents",
          status: "succeeded",
          latency_ms: 120,
          output: { hits: 3 },
        },
      },
      {
        event_type: "step_completed",
        run_id: RUN_ID,
        step_id: "step-1",
        timestamp: NOW,
        data: {
          step_name: "retrieve_documents",
          status: "completed",
          duration_ms: 200,
          outputs: { result_count: 3 },
        },
      },
      {
        event_type: "run_completed",
        run_id: RUN_ID,
        timestamp: NOW,
        data: {
          status: "completed",
          total_cost_usd: "0.001234",
          outcome: { answer: "Q3 revenue was $42M." },
        },
      },
    ],
    total_events: 6,
    step_count: 1,
    tool_call_count: 1,
    approval_count: 0,
    policy_snapshot: null,
    ...overrides,
  };
}

function makeExport(): AgentTraceExportResponse {
  return {
    run_id: RUN_ID,
    organization_id: "org-1",
    status: "completed",
    objective: "Summarise quarterly results",
    surface: "api",
    started_at: NOW,
    completed_at: NOW,
    cancelled_at: null,
    created_at: NOW,
    total_cost_usd: "0.001234",
    error_message: null,
    trace_request_id: "trace-xyz",
    steps: [
      {
        sequence: 0,
        step_name: "retrieve_documents",
        status: "completed",
        duration_ms: 200,
        error_message: null,
        started_at: NOW,
        completed_at: NOW,
      },
    ],
    tool_calls: [
      {
        tool_name: "search_documents",
        surface: "api",
        effect_policy: "read_only",
        status: "succeeded",
        attempt_number: 1,
        input_size_bytes: 50,
        output_size_bytes: 120,
        latency_ms: 120,
        started_at: NOW,
        completed_at: NOW,
      },
    ],
    approvals: [],
    export_safe: true,
    exported_at: NOW,
  };
}

function makeShareResponse(): AgentTraceShareResponse {
  return {
    token_id: "token-id-1",
    token: "raw-token-abc",
    expires_at: "2026-06-22T10:00:00.000Z",
    label: "Support ticket #123",
    share_url: "http://testserver/agent/traces/shared/raw-token-abc",
  };
}

function renderPage(runId = RUN_ID) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AgentTraceReplayPage runId={runId} />
    </QueryClientProvider>,
  );
}

// ── Tests ──────────────────────────────────────────────────────────────────────

describe("AgentTraceReplayPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows loading state initially", () => {
    mockApi.getAgentRunTrace.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders run summary header after loading", async () => {
    mockApi.getAgentRunTrace.mockResolvedValue(makeTrace());
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByText("Summarise quarterly results"),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("Trace Replay")).toBeInTheDocument();
  });

  it("renders timeline events", async () => {
    mockApi.getAgentRunTrace.mockResolvedValue(makeTrace());
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/6 events/i)).toBeInTheDocument(),
    );
    expect(screen.getAllByText(/Run Started/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Tool Called/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Run Completed/i).length).toBeGreaterThan(0);
  });

  it("expands event data on click", async () => {
    mockApi.getAgentRunTrace.mockResolvedValue(makeTrace());
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/Step Started/i)).toBeInTheDocument(),
    );
    const stepStartedRow = screen
      .getAllByRole("button")
      .find((btn) => btn.textContent?.includes("Step Started"));
    expect(stepStartedRow).toBeTruthy();
    await userEvent.click(stepStartedRow!);
    await waitFor(() =>
      expect(screen.getByText(/retrieve_documents/i)).toBeInTheDocument(),
    );
  });

  it("shows tool name in tool_called events", async () => {
    mockApi.getAgentRunTrace.mockResolvedValue(makeTrace());
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("search_documents")).toBeInTheDocument(),
    );
  });

  it("shows redaction banner when trace is redacted", async () => {
    mockApi.getAgentRunTrace.mockResolvedValue(makeTrace({ redacted: true }));
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByText(/redacted by your organisation/i),
      ).toBeInTheDocument(),
    );
  });

  it("shows shared_via_token banner for shared traces", async () => {
    mockApi.getAgentRunTrace.mockResolvedValue(
      makeTrace({ shared_via_token: true, redacted: true }),
    );
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/accessed via a share link/i)).toBeInTheDocument(),
    );
  });

  it("shows error state when API fails", async () => {
    mockApi.getAgentRunTrace.mockRejectedValue(new Error("Network error"));
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/Could not load trace/i)).toBeInTheDocument(),
    );
  });

  it("shows run error message in summary", async () => {
    mockApi.getAgentRunTrace.mockResolvedValue(
      makeTrace({ error_message: "Agent exceeded max steps" }),
    );
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/Agent exceeded max steps/i)).toBeInTheDocument(),
    );
  });

  it("triggers export download on Export button click", async () => {
    mockApi.getAgentRunTrace.mockResolvedValue(makeTrace());
    mockApi.exportAgentRunTrace.mockResolvedValue(makeExport());

    const createObjectURL = vi.fn().mockReturnValue("blob:test");
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { value: createObjectURL });
    Object.defineProperty(URL, "revokeObjectURL", { value: revokeObjectURL });

    const appendChildSpy = vi
      .spyOn(document.body, "appendChild")
      .mockImplementation((el) => el);
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    renderPage();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /export/i })).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByRole("button", { name: /export/i }));

    await waitFor(() =>
      expect(mockApi.exportAgentRunTrace).toHaveBeenCalledWith(RUN_ID),
    );
    appendChildSpy.mockRestore();
    clickSpy.mockRestore();
  });

  it("opens share modal on Share button click", async () => {
    mockApi.getAgentRunTrace.mockResolvedValue(makeTrace());
    renderPage();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /share/i })).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByRole("button", { name: /share/i }));
    expect(screen.getByRole("dialog", { name: /share trace/i })).toBeInTheDocument();
  });

  it("shows share link after successful share creation", async () => {
    mockApi.getAgentRunTrace.mockResolvedValue(makeTrace());
    mockApi.shareAgentRunTrace.mockResolvedValue(makeShareResponse());
    renderPage();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /share/i })).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByRole("button", { name: /share/i }));
    await userEvent.click(
      screen.getByRole("button", { name: /create link/i }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("dialog", { name: /share link created/i }),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByText("http://testserver/agent/traces/shared/raw-token-abc"),
    ).toBeInTheDocument();
  });

  it("shows empty state when timeline has no events", async () => {
    mockApi.getAgentRunTrace.mockResolvedValue(
      makeTrace({ timeline: [], total_events: 0 }),
    );
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByText(/No timeline events recorded/i),
      ).toBeInTheDocument(),
    );
  });
});
