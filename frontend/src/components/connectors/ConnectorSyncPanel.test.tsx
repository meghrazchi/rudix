import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConnectorSyncPanel } from "@/components/connectors/ConnectorSyncPanel";
import type {
  SyncJob,
  SyncRun,
  SyncJobsListResponse,
  SyncRunsListResponse,
  TriggerSyncNowResponse,
} from "@/lib/api/connector-sync";

// ── Mock: connector-sync API ──────────────────────────────────────────────────

const mockApi = vi.hoisted(() => ({
  listSyncJobs: vi.fn(),
  listSyncRuns: vi.fn(),
  createSyncJob: vi.fn(),
  updateSyncJobStatus: vi.fn(),
  triggerSyncNow: vi.fn(),
  cancelSyncRun: vi.fn(),
  getSyncJob: vi.fn(),
  getSyncRun: vi.fn(),
}));

vi.mock("@/lib/api/connector-sync", () => ({
  listSyncJobs: (...args: unknown[]) => mockApi.listSyncJobs(...args),
  listSyncRuns: (...args: unknown[]) => mockApi.listSyncRuns(...args),
  createSyncJob: (...args: unknown[]) => mockApi.createSyncJob(...args),
  updateSyncJobStatus: (...args: unknown[]) =>
    mockApi.updateSyncJobStatus(...args),
  triggerSyncNow: (...args: unknown[]) => mockApi.triggerSyncNow(...args),
  cancelSyncRun: (...args: unknown[]) => mockApi.cancelSyncRun(...args),
  getSyncJob: (...args: unknown[]) => mockApi.getSyncJob(...args),
  getSyncRun: (...args: unknown[]) => mockApi.getSyncRun(...args),
}));

// ── Helpers ───────────────────────────────────────────────────────────────────

const CONNECTION_ID = "conn-abc-123";

function makeJob(overrides: Partial<SyncJob> = {}): SyncJob {
  return {
    id: "job-1",
    organization_id: "org-1",
    connection_id: CONNECTION_ID,
    external_source_id: null,
    collection_id: null,
    name: "Hourly sync",
    status: "active",
    schedule: { type: "interval", interval_minutes: 60 },
    last_run_at: null,
    error_message: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

function makeRun(overrides: Partial<SyncRun> = {}): SyncRun {
  return {
    id: "run-1",
    organization_id: "org-1",
    sync_job_id: "job-1",
    connection_id: CONNECTION_ID,
    external_source_id: null,
    status: "completed",
    trigger_type: "manual",
    sync_version: 1000,
    started_at: new Date().toISOString(),
    completed_at: new Date().toISOString(),
    items_seen: 42,
    items_upserted: 10,
    items_deleted: 2,
    cursor_before: {},
    cursor_after: { page_token: "next" },
    error_message: null,
    error_details: {},
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

function makeJobsResponse(jobs: SyncJob[]): SyncJobsListResponse {
  return { items: jobs, total: jobs.length };
}

function makeRunsResponse(runs: SyncRun[]): SyncRunsListResponse {
  return { items: runs, total: runs.length };
}

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ConnectorSyncPanel connectionId={CONNECTION_ID} />
    </QueryClientProvider>,
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("ConnectorSyncPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.listSyncJobs.mockResolvedValue(makeJobsResponse([]));
    mockApi.listSyncRuns.mockResolvedValue(makeRunsResponse([]));
  });

  it("shows empty state when no jobs configured", async () => {
    renderPanel();
    await waitFor(() => {
      expect(
        screen.getByText(/No sync schedules configured/i),
      ).toBeInTheDocument();
    });
  });

  it("renders active sync job with Pause button", async () => {
    mockApi.listSyncJobs.mockResolvedValue(
      makeJobsResponse([makeJob({ status: "active" })]),
    );

    renderPanel();

    await waitFor(() => {
      expect(screen.getByText("Hourly sync")).toBeInTheDocument();
      expect(screen.getByText("active")).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /pause/i }),
      ).toBeInTheDocument();
    });
  });

  it("renders paused job with Resume button", async () => {
    mockApi.listSyncJobs.mockResolvedValue(
      makeJobsResponse([makeJob({ status: "paused" })]),
    );

    renderPanel();

    await waitFor(() => {
      expect(screen.getByText("paused")).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /resume/i }),
      ).toBeInTheDocument();
    });
  });

  it("shows Sync now button when active job exists", async () => {
    mockApi.listSyncJobs.mockResolvedValue(makeJobsResponse([makeJob()]));

    renderPanel();

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /sync now/i }),
      ).toBeInTheDocument();
    });
  });

  it("calls triggerSyncNow and invalidates runs query", async () => {
    mockApi.listSyncJobs.mockResolvedValue(makeJobsResponse([makeJob()]));
    const triggerResponse: TriggerSyncNowResponse = {
      sync_run_id: "run-new",
      status: "queued",
      message: "Sync queued",
    };
    mockApi.triggerSyncNow.mockResolvedValue(triggerResponse);
    mockApi.listSyncRuns.mockResolvedValue(makeRunsResponse([]));

    renderPanel();
    await waitFor(() => screen.getByRole("button", { name: /sync now/i }));

    await userEvent.click(screen.getByRole("button", { name: /sync now/i }));

    await waitFor(() => {
      expect(mockApi.triggerSyncNow).toHaveBeenCalledWith(
        CONNECTION_ID,
        "job-1",
      );
    });
  });

  it("calls updateSyncJobStatus when Pause clicked", async () => {
    mockApi.listSyncJobs.mockResolvedValue(
      makeJobsResponse([makeJob({ status: "active" })]),
    );
    mockApi.updateSyncJobStatus.mockResolvedValue(
      makeJob({ status: "paused" }),
    );

    renderPanel();
    await waitFor(() => screen.getByRole("button", { name: /pause/i }));

    await userEvent.click(screen.getByRole("button", { name: /pause/i }));

    await waitFor(() => {
      expect(mockApi.updateSyncJobStatus).toHaveBeenCalledWith(
        CONNECTION_ID,
        "job-1",
        "paused",
      );
    });
  });

  it("renders recent sync runs with stats", async () => {
    mockApi.listSyncRuns.mockResolvedValue(
      makeRunsResponse([
        makeRun({
          items_seen: 100,
          items_upserted: 20,
          items_deleted: 5,
          trigger_type: "scheduled",
        }),
      ]),
    );

    renderPanel();

    await waitFor(() => {
      expect(screen.getByText("100")).toBeInTheDocument();
      expect(screen.getByText("20")).toBeInTheDocument();
      expect(screen.getByText("5")).toBeInTheDocument();
      expect(screen.getByText("scheduled")).toBeInTheDocument();
      expect(screen.getByText("completed")).toBeInTheDocument();
    });
  });

  it("shows Cancel button for running run", async () => {
    mockApi.listSyncRuns.mockResolvedValue(
      makeRunsResponse([makeRun({ status: "running" })]),
    );

    renderPanel();

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /cancel/i }),
      ).toBeInTheDocument();
    });
  });

  it("calls cancelSyncRun when Cancel clicked", async () => {
    const runId = "run-abc";
    mockApi.listSyncRuns.mockResolvedValue(
      makeRunsResponse([makeRun({ id: runId, status: "running" })]),
    );
    mockApi.cancelSyncRun.mockResolvedValue(
      makeRun({ id: runId, status: "cancelled" }),
    );

    renderPanel();
    await waitFor(() => screen.getByRole("button", { name: /cancel/i }));

    await userEvent.click(screen.getByRole("button", { name: /cancel/i }));

    await waitFor(() => {
      expect(mockApi.cancelSyncRun).toHaveBeenCalledWith(runId);
    });
  });

  it("shows error message on trigger failure", async () => {
    mockApi.listSyncJobs.mockResolvedValue(makeJobsResponse([makeJob()]));
    mockApi.triggerSyncNow.mockRejectedValue(new Error("Already running"));

    renderPanel();
    await waitFor(() => screen.getByRole("button", { name: /sync now/i }));

    await userEvent.click(screen.getByRole("button", { name: /sync now/i }));

    await waitFor(() => {
      expect(screen.getByText(/already running/i)).toBeInTheDocument();
    });
  });

  it("displays schedule interval in human-readable form", async () => {
    mockApi.listSyncJobs.mockResolvedValue(
      makeJobsResponse([
        makeJob({
          schedule: { type: "interval", interval_minutes: 30 },
        }),
      ]),
    );

    renderPanel();

    await waitFor(() => {
      expect(screen.getByText(/every 30 min/i)).toBeInTheDocument();
    });
  });
});
