import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminAgentPolicyPage } from "@/components/admin/AdminAgentPolicyPage";
import type { SessionState } from "@/lib/auth-session";

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  getAgentPolicy: vi.fn(),
  upsertToolPolicy: vi.fn(),
  deleteToolPolicy: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    session:
      mockState.authState.status === "authenticated"
        ? mockState.authState.session
        : null,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/admin-agent-policy", () => ({
  getAgentPolicy: () => mockApi.getAgentPolicy(),
  upsertToolPolicy: (name: string, payload: unknown) =>
    mockApi.upsertToolPolicy(name, payload),
  deleteToolPolicy: (name: string) => mockApi.deleteToolPolicy(name),
}));

const MOCK_POLICY = {
  organization_id: "org-1",
  org_budget: {
    max_steps: 10,
    max_tool_calls_per_run: 50,
    max_total_tokens: null,
    max_total_cost_usd: null,
  },
  tool_overrides: [],
  resolved_tools: [
    {
      tool_name: "search.documents",
      enabled: true,
      approval_required: false,
      required_roles: ["viewer"],
      max_calls_per_run: 20,
      max_input_bytes: 32768,
      max_output_bytes: 65536,
      timeout_ms: 8000,
      max_retry_attempts: 1,
      is_overridden: false,
    },
    {
      tool_name: "create.note",
      enabled: true,
      approval_required: true,
      required_roles: ["owner", "admin"],
      max_calls_per_run: 5,
      max_input_bytes: 4096,
      max_output_bytes: 4096,
      timeout_ms: 5000,
      max_retry_attempts: 0,
      is_overridden: false,
    },
  ],
  policy_updated_at: "2026-06-19T10:00:00Z",
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
      <AdminAgentPolicyPage />
    </QueryClientProvider>,
  );
}

describe("AdminAgentPolicyPage", () => {
  beforeEach(() => {
    mockApi.getAgentPolicy.mockReset();
    mockApi.upsertToolPolicy.mockReset();
    mockApi.deleteToolPolicy.mockReset();
    mockApi.getAgentPolicy.mockResolvedValue(MOCK_POLICY);
  });

  it("renders tool list and org budget section for admins", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-1",
        email: "admin@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "tok",
      },
    };

    renderPage();

    expect(
      await screen.findByText("Agent tool policy & budgets"),
    ).toBeInTheDocument();
    expect(await screen.findByText("search.documents")).toBeInTheDocument();
    expect(await screen.findByText("create.note")).toBeInTheDocument();
    expect(
      await screen.findByText("Org-level budget limits"),
    ).toBeInTheDocument();
    expect(await screen.findByText("10")).toBeInTheDocument(); // max_steps
  });

  it("shows forbidden state for unauthenticated users", async () => {
    mockState.authState = { status: "unauthenticated", session: null };
    renderPage();
    expect(
      await screen.findByText(/forbidden|permission|access/i),
    ).toBeInTheDocument();
  });

  it("shows error state when API fails", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-1",
        email: "admin@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "tok",
      },
    };
    mockApi.getAgentPolicy.mockRejectedValue(new Error("Server error"));
    renderPage();
    expect(await screen.findByText(/error|server error/i)).toBeInTheDocument();
  });

  it("shows 'unlimited' for null budget values", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-1",
        email: "admin@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "tok",
      },
    };

    renderPage();

    const unlimitedItems = await screen.findAllByText("unlimited");
    expect(unlimitedItems.length).toBeGreaterThan(0);
  });

  it("opens edit form when Edit is clicked", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-1",
        email: "admin@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "tok",
      },
    };

    renderPage();

    const editButtons = await screen.findAllByText("Edit");
    fireEvent.click(editButtons[0]!);

    expect(await screen.findByText("Save override")).toBeInTheDocument();
  });

  it("calls upsertToolPolicy on save", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-1",
        email: "admin@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "tok",
      },
    };
    mockApi.upsertToolPolicy.mockResolvedValue({
      organization_id: "org-1",
      override: { tool_name: "search.documents", enabled: false },
      audit_recorded: true,
    });

    renderPage();

    const editButtons = await screen.findAllByText("Edit");
    fireEvent.click(editButtons[0]!);

    const saveBtn = await screen.findByText("Save override");
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(mockApi.upsertToolPolicy).toHaveBeenCalledTimes(1);
    });
  });

  it("cancel closes the edit form", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-1",
        email: "admin@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "tok",
      },
    };

    renderPage();

    const editButtons = await screen.findAllByText("Edit");
    fireEvent.click(editButtons[0]!);
    expect(await screen.findByText("Save override")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Cancel"));

    await waitFor(() => {
      expect(screen.queryByText("Save override")).not.toBeInTheDocument();
    });
  });

  it("displays 'Custom' badge for overridden tools", async () => {
    const policyWithOverride = {
      ...MOCK_POLICY,
      tool_overrides: [
        {
          tool_name: "search.documents",
          enabled: false,
          updated_at: "2026-06-19T10:00:00Z",
        },
      ],
      resolved_tools: [
        { ...MOCK_POLICY.resolved_tools[0]!, is_overridden: true },
        MOCK_POLICY.resolved_tools[1]!,
      ],
    };
    mockApi.getAgentPolicy.mockResolvedValue(policyWithOverride);

    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-1",
        email: "admin@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "tok",
      },
    };

    renderPage();

    expect(await screen.findByText("Custom")).toBeInTheDocument();
  });

  it("shows 'Default' label for non-overridden tools", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-1",
        email: "admin@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "tok",
      },
    };

    renderPage();

    const defaultLabels = await screen.findAllByText("Default");
    expect(defaultLabels.length).toBe(2);
  });

  it("shows last updated timestamp", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-1",
        email: "admin@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "tok",
      },
    };

    renderPage();

    expect(await screen.findByText(/last updated/i)).toBeInTheDocument();
  });

  it("shows approval required state in table", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-1",
        email: "admin@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "tok",
      },
    };

    renderPage();

    await screen.findByText("search.documents");
    const yesItems = await screen.findAllByText("Yes");
    expect(yesItems.length).toBeGreaterThan(0); // create.note has approval_required: true
  });

  it("upsert mutation error is shown inline", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-1",
        email: "admin@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "tok",
      },
    };
    mockApi.upsertToolPolicy.mockRejectedValue(new Error("Policy save failed"));

    renderPage();

    const editButtons = await screen.findAllByText("Edit");
    fireEvent.click(editButtons[0]!);
    fireEvent.click(await screen.findByText("Save override"));

    expect(await screen.findByText(/policy save failed/i)).toBeInTheDocument();
  });

  it("renders link to governance page in description", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-1",
        email: "admin@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "tok",
      },
    };

    renderPage();

    await screen.findByText("Agent tool policy & budgets");
    const govLink = screen.getAllByRole("link", { name: /governance/i });
    expect(govLink.length).toBeGreaterThan(0);
  });
});
