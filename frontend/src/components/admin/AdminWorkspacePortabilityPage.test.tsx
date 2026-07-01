import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminWorkspacePortabilityPage } from "@/components/admin/AdminWorkspacePortabilityPage";
import type { SessionState } from "@/lib/auth-session";
import type { WorkspacePortabilityJobList } from "@/lib/api/workspace-portability";

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  listWorkspacePortabilityJobs: vi.fn(),
  createWorkspaceExport: vi.fn(),
  createWorkspaceImport: vi.fn(),
  downloadWorkspacePortabilityArtifact: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/workspace-portability", async (importOriginal) => {
  const original =
    await importOriginal<typeof import("@/lib/api/workspace-portability")>();
  return {
    ...original,
    listWorkspacePortabilityJobs: (query?: unknown) =>
      mockApi.listWorkspacePortabilityJobs(query),
    createWorkspaceExport: (payload: unknown) =>
      mockApi.createWorkspaceExport(payload),
    createWorkspaceImport: (payload: unknown) =>
      mockApi.createWorkspaceImport(payload),
    downloadWorkspacePortabilityArtifact: (jobId: string) =>
      mockApi.downloadWorkspacePortabilityArtifact(jobId),
  };
});

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <AdminWorkspacePortabilityPage />
    </QueryClientProvider>,
  );
}

function makeAdminSession(): SessionState {
  return {
    status: "authenticated",
    session: {
      userId: "user-1",
      email: "admin@example.com",
      organizationId: "org-1",
      organizationName: "Org 1",
      role: "admin",
      accessToken: "token-1",
    },
  };
}

const jobsResponse: WorkspacePortabilityJobList = {
  items: [
    {
      job_id: "job-1",
      organization_id: "org-1",
      created_by_user_id: "user-1",
      job_type: "export",
      status: "completed",
      requested_sections: ["collections", "api_metadata"],
      parameters: {},
      artifact_filename: "rudix-workspace-export-job-1.json",
      artifact_mime_type: "application/json",
      artifact_size_bytes: 2048,
      validation_errors: [],
      warnings: [],
      error_message: null,
      records_processed: 4,
      records_failed: 0,
      created_at: "2026-07-01T10:00:00Z",
      updated_at: "2026-07-01T10:00:00Z",
      started_at: "2026-07-01T10:00:00Z",
      completed_at: "2026-07-01T10:00:01Z",
      expires_at: "2026-07-08T10:00:01Z",
      download_available: true,
    },
  ],
  total: 1,
  limit: 25,
  offset: 0,
};

beforeEach(() => {
  vi.clearAllMocks();
  mockState.authState = makeAdminSession();
  mockApi.listWorkspacePortabilityJobs.mockResolvedValue(jobsResponse);
  mockApi.createWorkspaceExport.mockResolvedValue(jobsResponse.items[0]);
  mockApi.createWorkspaceImport.mockResolvedValue({
    ...jobsResponse.items[0],
    job_id: "job-2",
    job_type: "import",
    status: "validated",
    requested_sections: ["collections"],
  });
  mockApi.downloadWorkspacePortabilityArtifact.mockResolvedValue(
    new Blob(["{}"], { type: "application/json" }),
  );
});

describe("AdminWorkspacePortabilityPage", () => {
  it("renders jobs and can request an export", async () => {
    renderPage();

    expect(
      await screen.findByText("Import and export data"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("rudix-workspace-export-job-1.json"),
    ).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Create export job" }),
    );

    await waitFor(() => {
      expect(mockApi.createWorkspaceExport).toHaveBeenCalledWith(
        expect.objectContaining({
          sections: expect.arrayContaining(["collections", "api_metadata"]),
          max_rows_per_section: 5000,
        }),
      );
    });
  });

  it("validates import JSON before calling API", async () => {
    renderPage();
    await screen.findByText("rudix-workspace-export-job-1.json");

    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "{bad json" },
    });
    await userEvent.click(
      screen.getByRole("button", { name: "Validate import" }),
    );

    expect(
      await screen.findByText(/Expected property name|Unexpected token/i),
    ).toBeInTheDocument();
    expect(mockApi.createWorkspaceImport).not.toHaveBeenCalled();
  });

  it("renders forbidden state for non-admin users", () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "user-2",
        email: "member@example.com",
        organizationId: "org-1",
        organizationName: "Org 1",
        role: "member",
      },
    };

    renderPage();
    expect(
      screen.getByText("Workspace portability restricted"),
    ).toBeInTheDocument();
  });
});
