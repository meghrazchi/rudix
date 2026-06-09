import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminModelDiagnosticsPage } from "@/components/admin/AdminModelDiagnosticsPage";
import type { SessionState } from "@/lib/auth-session";
import type {
  ModelProviderDiagnosticsResponse,
  TestProviderResponse,
} from "@/lib/api/model-provider-diagnostics";

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  getModelProviderDiagnostics: vi.fn(),
  testModelProviderConnection: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/model-provider-diagnostics", () => ({
  getModelProviderDiagnostics: () => mockApi.getModelProviderDiagnostics(),
  testModelProviderConnection: (payload: unknown) =>
    mockApi.testModelProviderConnection(payload),
}));

const ADMIN_SESSION: SessionState = {
  status: "authenticated",
  session: {
    userId: "u1",
    organizationId: "org-1",
    organizationName: "Test Org",
    role: "admin",
    email: "admin@test.com",
  },
};

const MEMBER_SESSION: SessionState = {
  status: "authenticated",
  session: {
    userId: "u2",
    organizationId: "org-1",
    organizationName: "Test Org",
    role: "member",
    email: "member@test.com",
  },
};

const PROVIDERS_RESPONSE: ModelProviderDiagnosticsResponse = {
  providers: [
    {
      provider_key: "chat",
      provider_type: "openai",
      model_name: "gpt-4o",
      is_configured: true,
      task_assignments: ["chat", "summarization", "comparison", "evaluations", "agentic"],
      capability: {
        context_window: 128000,
        supports_json_mode: true,
        supports_tool_calling: true,
        supports_streaming: true,
        is_embedding_model: false,
        embedding_dimension: null,
        cost_behavior: "per_token",
      },
      reindex_required: false,
    },
    {
      provider_key: "embeddings",
      provider_type: "openai",
      model_name: "text-embedding-3-small",
      is_configured: true,
      task_assignments: ["embeddings"],
      capability: {
        context_window: 8191,
        supports_json_mode: false,
        supports_tool_calling: false,
        supports_streaming: false,
        is_embedding_model: true,
        embedding_dimension: 1536,
        cost_behavior: "per_token",
      },
      reindex_required: false,
    },
  ],
};

const TEST_OK_RESPONSE: TestProviderResponse = {
  provider_key: "chat",
  provider_type: "openai",
  model_name: "gpt-4o",
  status: "ok",
  latency_ms: 123,
  error_code: null,
  error_message: null,
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
      <AdminModelDiagnosticsPage />
    </QueryClientProvider>,
  );
}

describe("AdminModelDiagnosticsPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockState.authState = ADMIN_SESSION;
    mockApi.getModelProviderDiagnostics.mockResolvedValue(PROVIDERS_RESPONSE);
    mockApi.testModelProviderConnection.mockResolvedValue(TEST_OK_RESPONSE);
  });

  it("shows forbidden state for unauthenticated users", () => {
    mockState.authState = { status: "unauthenticated", session: null };
    renderPage();
    expect(screen.getByText(/restricted/i)).toBeTruthy();
  });

  it("shows loading state while query is in flight", () => {
    mockApi.getModelProviderDiagnostics.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByText(/loading provider diagnostics/i)).toBeTruthy();
  });

  it("shows error state when fetch fails", async () => {
    mockApi.getModelProviderDiagnostics.mockRejectedValue(new Error("network error"));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/unable to load provider diagnostics/i)).toBeTruthy();
    });
  });

  it("renders both provider cards after load", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("gpt-4o")).toBeTruthy();
    });
    expect(screen.getByText("text-embedding-3-small")).toBeTruthy();
  });

  it("shows Generation and Embeddings section labels", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/generation provider/i)).toBeTruthy();
    });
    expect(screen.getByText(/embeddings provider/i)).toBeTruthy();
  });

  it("shows Configured badge when is_configured=true", async () => {
    renderPage();
    await waitFor(() => {
      const badges = screen.getAllByText("Configured");
      expect(badges.length).toBe(2);
    });
  });

  it("shows Not configured badge when is_configured=false", async () => {
    mockApi.getModelProviderDiagnostics.mockResolvedValue({
      providers: [
        {
          ...PROVIDERS_RESPONSE.providers[0],
          is_configured: false,
        },
        PROVIDERS_RESPONSE.providers[1],
      ],
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Not configured")).toBeTruthy();
    });
  });

  it("shows task assignment chips", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("chat")).toBeTruthy();
    });
    expect(screen.getByText("embeddings")).toBeTruthy();
  });

  it("shows capability badges for a known model", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("JSON mode")).toBeTruthy();
    });
    expect(screen.getByText("Tool calling")).toBeTruthy();
  });

  it("shows embedding dimension badge", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("1536d")).toBeTruthy();
    });
  });

  it("shows reindex warning when reindex_required=true", async () => {
    mockApi.getModelProviderDiagnostics.mockResolvedValue({
      providers: [
        PROVIDERS_RESPONSE.providers[0],
        {
          ...PROVIDERS_RESPONSE.providers[1],
          reindex_required: true,
        },
      ],
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/re-index is required/i)).toBeTruthy();
    });
  });

  it("shows Test connection button for admin", async () => {
    renderPage();
    await waitFor(() => {
      const buttons = screen.getAllByText("Test connection");
      expect(buttons.length).toBe(2);
    });
  });

  it("does not show Test connection button for member", async () => {
    mockState.authState = MEMBER_SESSION;
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("gpt-4o")).toBeTruthy();
    });
    expect(screen.queryByText("Test connection")).toBeNull();
  });

  it("calls testModelProviderConnection when Test connection clicked", async () => {
    renderPage();
    await waitFor(() => screen.getAllByText("Test connection"));

    const buttons = screen.getAllByText("Test connection");
    fireEvent.click(buttons[0]);

    await waitFor(() => {
      expect(mockApi.testModelProviderConnection).toHaveBeenCalledWith({
        provider_key: "chat",
      });
    });
  });

  it("shows Connected status and latency after successful test", async () => {
    renderPage();
    await waitFor(() => screen.getAllByText("Test connection"));

    fireEvent.click(screen.getAllByText("Test connection")[0]);

    await waitFor(() => {
      expect(screen.getByText("Connected")).toBeTruthy();
    });
    expect(screen.getByText("123 ms")).toBeTruthy();
  });

  it("shows error status after failed test", async () => {
    mockApi.testModelProviderConnection.mockResolvedValue({
      ...TEST_OK_RESPONSE,
      status: "configuration_error",
      error_code: "configuration_error",
      error_message: "Provider is not configured in the environment.",
    });
    renderPage();
    await waitFor(() => screen.getAllByText("Test connection"));

    fireEvent.click(screen.getAllByText("Test connection")[0]);

    await waitFor(() => {
      expect(screen.getByText("Not configured")).toBeTruthy();
    });
    expect(
      screen.getByText("Provider is not configured in the environment."),
    ).toBeTruthy();
  });

  it("shows empty state when providers list is empty", async () => {
    mockApi.getModelProviderDiagnostics.mockResolvedValue({ providers: [] });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/no provider configuration found/i)).toBeTruthy();
    });
  });
});
