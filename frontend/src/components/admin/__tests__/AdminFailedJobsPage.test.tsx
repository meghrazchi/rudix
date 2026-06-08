import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminFailedJobsPage } from "@/components/admin/AdminFailedJobsPage";
import type { SessionState } from "@/lib/auth-session";
import type {
  FailedJobDetail,
  FailedJobsListResponse,
} from "@/lib/api/failed-jobs";

const mockAuth = vi.hoisted(() => ({
  state: {
    status: "authenticated",
    session: null,
  } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  listFailedJobs: vi.fn(),
  getFailedJob: vi.fn(),
  retryFailedJob: vi.fn(),
  cancelFailedJob: vi.fn(),
  resolveFailedJob: vi.fn(),
  bulkRetryFailedJobs: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({ state: mockAuth.state }),
}));

vi.mock("@/lib/api/failed-jobs", () => ({
  listFailedJobs: (...args: unknown[]) => mockApi.listFailedJobs(...args),
  getFailedJob: (...args: unknown[]) => mockApi.getFailedJob(...args),
  retryFailedJob: (...args: unknown[]) => mockApi.retryFailedJob(...args),
  cancelFailedJob: (...args: unknown[]) => mockApi.cancelFailedJob(...args),
  resolveFailedJob: (...args: unknown[]) => mockApi.resolveFailedJob(...args),
  bulkRetryFailedJobs: (...args: unknown[]) =>
    mockApi.bulkRetryFailedJobs(...args),
}));

const EMPTY_LIST: FailedJobsListResponse = {
  items: [],
  total: 0,
  page: 1,
  page_size: 25,
};

const FAILED_JOB_SUMMARY = {
  id: "job-1",
  organization_id: "org-1",
  task_id: "task-abc",
  task_name: "documents.process",
  job_type: "extraction",
  status: "failed" as const,
  queue_name: "documents_processing",
  error_code: "TimeoutError",
  attempt_count: 2,
  is_retryable: true,
  entity_type: "document",
  entity_id: "doc-1",
  last_attempted_at: "2026-06-05T10:00:00Z",
  resolved_at: null,
  created_at: "2026-06-05T09:00:00Z",
  updated_at: "2026-06-05T10:00:00Z",
};

const FAILED_JOB_DETAIL: FailedJobDetail = {
  ...FAILED_JOB_SUMMARY,
  error_message: "Connection timed out after 30s",
  metadata_json: {},
  audit_log: [],
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AdminFailedJobsPage />
    </QueryClientProvider>,
  );
}

describe("AdminFailedJobsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuth.state = {
      status: "authenticated",
      session: {
        userId: "user-1",
        email: "admin@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Org One",
      },
    };
  });

  it("shows forbidden state for non-admin roles", async () => {
    mockAuth.state = {
      status: "authenticated",
      session: {
        userId: "user-2",
        email: "member@example.com",
        role: "member",
        organizationId: "org-1",
        organizationName: "Org One",
      },
    };
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/admin access restricted/i)).toBeInTheDocument();
    });
  });

  it("shows empty state when there are no failed jobs", async () => {
    mockApi.listFailedJobs.mockResolvedValue(EMPTY_LIST);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/no failed jobs match/i)).toBeInTheDocument();
    });
  });

  it("renders a row for each failed job", async () => {
    mockApi.listFailedJobs.mockResolvedValue({
      ...EMPTY_LIST,
      items: [FAILED_JOB_SUMMARY],
      total: 1,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("TimeoutError")).toBeInTheDocument();
      expect(screen.getByText("documents.process")).toBeInTheDocument();
    });
  });

  it("shows status badge for each job", async () => {
    mockApi.listFailedJobs.mockResolvedValue({
      ...EMPTY_LIST,
      items: [FAILED_JOB_SUMMARY],
      total: 1,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("failed")).toBeInTheDocument();
    });
  });

  it("opens detail drawer when View button is clicked", async () => {
    mockApi.listFailedJobs.mockResolvedValue({
      ...EMPTY_LIST,
      items: [FAILED_JOB_SUMMARY],
      total: 1,
    });
    mockApi.getFailedJob.mockResolvedValue(FAILED_JOB_DETAIL);
    renderPage();

    const viewBtn = await screen.findByRole("button", { name: /view/i });
    await userEvent.click(viewBtn);

    await waitFor(() => {
      expect(screen.getByText("Job detail")).toBeInTheDocument();
      expect(screen.getByText(/connection timed out/i)).toBeInTheDocument();
    });
  });

  it("shows Retry button for retryable failed jobs in drawer", async () => {
    mockApi.listFailedJobs.mockResolvedValue({
      ...EMPTY_LIST,
      items: [FAILED_JOB_SUMMARY],
      total: 1,
    });
    mockApi.getFailedJob.mockResolvedValue(FAILED_JOB_DETAIL);
    renderPage();

    const viewBtn = await screen.findByRole("button", { name: /view/i });
    await userEvent.click(viewBtn);

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /^retry$/i }),
      ).toBeInTheDocument();
    });
  });

  it("does not show Retry button for non-retryable jobs", async () => {
    const nonRetryable = { ...FAILED_JOB_DETAIL, is_retryable: false };
    mockApi.listFailedJobs.mockResolvedValue({
      ...EMPTY_LIST,
      items: [{ ...FAILED_JOB_SUMMARY, is_retryable: false }],
      total: 1,
    });
    mockApi.getFailedJob.mockResolvedValue(nonRetryable);
    renderPage();

    const viewBtn = await screen.findByRole("button", { name: /view/i });
    await userEvent.click(viewBtn);

    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /^retry$/i })).toBeNull();
    });
  });

  it("enables Bulk retry button when jobs are selected", async () => {
    mockApi.listFailedJobs.mockResolvedValue({
      ...EMPTY_LIST,
      items: [FAILED_JOB_SUMMARY],
      total: 1,
    });
    renderPage();

    const checkbox = await screen.findByRole("checkbox", {
      name: /select job/i,
    });
    await userEvent.click(checkbox);

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /bulk retry/i }),
      ).toBeInTheDocument();
    });
  });

  it("shows pagination controls when total exceeds page size", async () => {
    const items = Array.from({ length: 25 }, (_, i) => ({
      ...FAILED_JOB_SUMMARY,
      id: `job-${i}`,
    }));
    mockApi.listFailedJobs.mockResolvedValue({
      items,
      total: 30,
      page: 1,
      page_size: 25,
    });
    renderPage();

    await waitFor(() => {
      expect(screen.getByText(/30 total/)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /next/i })).toBeInTheDocument();
    });
  });

  it("shows audit log entries in drawer when present", async () => {
    mockApi.listFailedJobs.mockResolvedValue({
      ...EMPTY_LIST,
      items: [FAILED_JOB_SUMMARY],
      total: 1,
    });
    mockApi.getFailedJob.mockResolvedValue({
      ...FAILED_JOB_DETAIL,
      audit_log: [
        {
          id: "audit-1",
          action: "retry",
          performed_by_id: "user-1",
          note: null,
          created_at: "2026-06-05T10:30:00Z",
        },
      ],
    });
    renderPage();

    const viewBtn = await screen.findByRole("button", { name: /view/i });
    await userEvent.click(viewBtn);

    await waitFor(() => {
      expect(screen.getByText("Audit log")).toBeInTheDocument();
      expect(screen.getByText("retry")).toBeInTheDocument();
    });
  });
});
