import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminOrgMemoryPage } from "@/components/admin/AdminOrgMemoryPage";
import type { SessionState } from "@/lib/auth-session";
import type {
  WorkflowListResponse,
  WorkflowResponse,
} from "@/lib/api/org-memory";

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  adminListWorkflows: vi.fn(),
  adminArchiveWorkflow: vi.fn(),
  adminDeleteWorkflow: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/org-memory", async (importOriginal) => {
  const original =
    await importOriginal<typeof import("@/lib/api/org-memory")>();
  return {
    ...original,
    adminListWorkflows: (params?: unknown) =>
      mockApi.adminListWorkflows(params),
    adminArchiveWorkflow: (workflowId: string) =>
      mockApi.adminArchiveWorkflow(workflowId),
    adminDeleteWorkflow: (workflowId: string) =>
      mockApi.adminDeleteWorkflow(workflowId),
  };
});

function makeAdminSession(role: "admin" | "owner" = "admin"): SessionState {
  return {
    status: "authenticated",
    session: {
      userId: "user-1",
      email: "admin@example.com",
      organizationId: "org-1",
      organizationName: "Org 1",
      role,
    },
  };
}

function makeWorkflow(
  overrides: Partial<WorkflowResponse> = {},
): WorkflowResponse {
  return {
    workflow_id: "workflow-1",
    organization_id: "org-1",
    created_by_id: "user-1",
    name: "Audit evidence pack",
    description: "Reusable audit evidence workflow",
    workflow_type: "audit_evidence_pack",
    status: "active",
    steps: [
      {
        label: "Collect evidence",
        query_template: "Find audit evidence for the quarter",
        scope: "collection",
        collection_ids: ["collection-1"],
      },
    ],
    role_scope: ["owner", "admin"],
    collection_scope_ids: ["collection-1"],
    verified_knowledge_card_id: "card-1",
    use_count: 3,
    created_at: "2026-06-20T10:00:00Z",
    updated_at: "2026-06-20T10:00:00Z",
    ...overrides,
  };
}

function makeListResponse(
  items: WorkflowResponse[] = [makeWorkflow()],
): WorkflowListResponse {
  return {
    items,
    total: items.length,
    limit: 50,
    offset: 0,
  };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <AdminOrgMemoryPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockState.authState = makeAdminSession();
  mockApi.adminListWorkflows.mockResolvedValue(makeListResponse());
  mockApi.adminArchiveWorkflow.mockResolvedValue(
    makeWorkflow({ status: "archived" }),
  );
  mockApi.adminDeleteWorkflow.mockResolvedValue(undefined);
});

describe("AdminOrgMemoryPage", () => {
  it("renders saved workflows for admins", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Org Memory")).toBeInTheDocument();
    });
    expect(screen.getByText("Audit evidence pack")).toBeInTheDocument();
    expect(
      screen.getByText("Reusable audit evidence workflow"),
    ).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("blocks non-admin users", async () => {
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

    await waitFor(() => {
      expect(screen.getByText("Forbidden")).toBeInTheDocument();
    });
    expect(mockApi.adminListWorkflows).not.toHaveBeenCalled();
  });

  it("can archive and delete workflows", async () => {
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Audit evidence pack")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Archive" }));
    await waitFor(() => {
      expect(mockApi.adminArchiveWorkflow).toHaveBeenCalledWith("workflow-1");
    });

    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Confirm delete" }));
    await waitFor(() => {
      expect(mockApi.adminDeleteWorkflow).toHaveBeenCalledWith("workflow-1");
    });
  });
});
