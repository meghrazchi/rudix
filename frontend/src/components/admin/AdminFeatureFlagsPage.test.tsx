import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminFeatureFlagsPage } from "@/components/admin/AdminFeatureFlagsPage";
import { ApiClientError } from "@/lib/api/errors";
import type { SessionState } from "@/lib/auth-session";
import type {
  FeatureFlagDetail,
  FeatureFlagsResponse,
} from "@/lib/api/feature-flags";

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  listAdminFeatureFlags: vi.fn(),
  setAdminFeatureFlag: vi.fn(),
  clearAdminFeatureFlag: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/feature-flags", async (importOriginal) => {
  const original =
    await importOriginal<typeof import("@/lib/api/feature-flags")>();
  return {
    ...original,
    listAdminFeatureFlags: () => mockApi.listAdminFeatureFlags(),
    setAdminFeatureFlag: (name: string, body: unknown) =>
      mockApi.setAdminFeatureFlag(name, body),
    clearAdminFeatureFlag: (name: string) =>
      mockApi.clearAdminFeatureFlag(name),
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

function makeFlag(
  name: string,
  enabled: boolean,
  envDefault: boolean,
  hasOverride = false,
): FeatureFlagDetail {
  return {
    name,
    enabled,
    env_default: envDefault,
    has_org_override: hasOverride,
    override_enabled: hasOverride ? enabled : null,
    override_reason: hasOverride ? "Test reason" : null,
    overridden_by_user_id: hasOverride ? "user-1" : null,
    overridden_at: hasOverride ? new Date().toISOString() : null,
  };
}

const mockFlagsResponse: FeatureFlagsResponse = {
  organization_id: "org-1",
  flags: [
    makeFlag("agents", false, false),
    makeFlag("mcp", false, false),
    makeFlag("connectors", true, true),
    makeFlag("evaluations", false, true, true),
    makeFlag("chunking_profiles", false, false),
    makeFlag("adaptive_chunking", false, false),
    makeFlag("graph_rag", false, false),
    makeFlag("graph_extraction", true, false),
    makeFlag("graph_explorer", true, true),
    makeFlag("advanced_pdf_extraction", true, true),
    makeFlag("language_aware_rag", true, true),
    makeFlag("pipeline_explorer", true, true),
    makeFlag("local_llm_profiles", false, false),
    makeFlag("experimental_profiles", false, false),
    makeFlag("provider_fallback", false, false),
    makeFlag("external_mcp_connectors", false, false),
    makeFlag("query_rewrite_preview", true, true),
    makeFlag("org_memory", false, false),
  ],
};

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

function renderPage() {
  const qc = makeQueryClient();
  render(
    <QueryClientProvider client={qc}>
      <AdminFeatureFlagsPage />
    </QueryClientProvider>,
  );
  return qc;
}

beforeEach(() => {
  vi.clearAllMocks();
  mockState.authState = makeAdminSession();
});

describe("AdminFeatureFlagsPage", () => {
  it("shows loading state initially", () => {
    mockApi.listAdminFeatureFlags.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByText(/Loading feature flags/i)).toBeInTheDocument();
  });

  it("shows forbidden when user is not admin", async () => {
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
    mockApi.listAdminFeatureFlags.mockResolvedValue(mockFlagsResponse);
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/Admin area restricted/i)).toBeInTheDocument(),
    );
  });

  it("renders all flag rows after successful load", async () => {
    mockApi.listAdminFeatureFlags.mockResolvedValue(mockFlagsResponse);
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Agentic mode")).toBeInTheDocument(),
    );
    expect(screen.getByText("Connectors")).toBeInTheDocument();
    expect(screen.getByText("Evaluations")).toBeInTheDocument();
    expect(screen.getByText("MCP integration")).toBeInTheDocument();
    expect(screen.getByText("Query rewrite preview")).toBeInTheDocument();
  });

  it("shows error state on API failure", async () => {
    mockApi.listAdminFeatureFlags.mockRejectedValue(
      new ApiClientError({
        status: 500,
        code: "unknown_error",
        message: "Server error",
        details: null,
        requestId: null,
        userMessage: "Something went wrong while contacting the API.",
        actionMessage: "Try again.",
        retryable: false,
      }),
    );
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByText(/Something went wrong while contacting the API/i),
      ).toBeInTheDocument(),
    );
  });

  it("shows forbidden state on 403 response", async () => {
    mockApi.listAdminFeatureFlags.mockRejectedValue(
      new ApiClientError({
        status: 403,
        code: "forbidden",
        message: "Forbidden",
        details: null,
        requestId: null,
        userMessage: "You do not have permission for this action.",
        actionMessage: "Switch organization or contact an administrator.",
        retryable: false,
      }),
    );
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/Access denied/i)).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/You do not have permission to manage feature flags\./i),
    ).toBeInTheDocument();
  });

  it("shows inline error when set mutation fails", async () => {
    mockApi.listAdminFeatureFlags.mockResolvedValue(mockFlagsResponse);
    mockApi.setAdminFeatureFlag.mockRejectedValue(new Error("Save failed"));
    const user = userEvent.setup();
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Connectors")).toBeInTheDocument(),
    );

    const disableButtons = screen.getAllByRole("button", {
      name: /^Disable$/i,
    });
    await user.click(disableButtons[0]);
    await user.click(screen.getByRole("button", { name: /Confirm/i }));

    await waitFor(() =>
      expect(screen.getByText(/Save failed/i)).toBeInTheDocument(),
    );
  });

  it("shows 'Reset to default' only for flags with org override", async () => {
    mockApi.listAdminFeatureFlags.mockResolvedValue(mockFlagsResponse);
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Agentic mode")).toBeInTheDocument(),
    );
    const resetButtons = screen.getAllByRole("button", {
      name: /Reset to default/i,
    });
    // Only "evaluations" has has_org_override=true in mockFlagsResponse
    expect(resetButtons).toHaveLength(1);
  });

  it("opens confirm modal when Disable is clicked", async () => {
    mockApi.listAdminFeatureFlags.mockResolvedValue(mockFlagsResponse);
    const user = userEvent.setup();
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Connectors")).toBeInTheDocument(),
    );

    // connectors is enabled → should have "Disable" button
    const disableButtons = screen.getAllByRole("button", {
      name: /^Disable$/i,
    });
    await user.click(disableButtons[0]);

    expect(screen.getByText(/Disable "Connectors"/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Confirm/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Cancel/i })).toBeInTheDocument();
  });

  it("calls setAdminFeatureFlag on confirm and dismisses modal", async () => {
    const updatedFlag = makeFlag("connectors", false, true, true);
    mockApi.listAdminFeatureFlags.mockResolvedValue(mockFlagsResponse);
    mockApi.setAdminFeatureFlag.mockResolvedValue({
      organization_id: "org-1",
      flag: updatedFlag,
    });
    const user = userEvent.setup();
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Connectors")).toBeInTheDocument(),
    );

    const disableButtons = screen.getAllByRole("button", {
      name: /^Disable$/i,
    });
    await user.click(disableButtons[0]);

    const reasonInput = screen.getByPlaceholderText(
      /Why is this change needed/i,
    );
    await user.type(reasonInput, "Maintenance window");

    await user.click(screen.getByRole("button", { name: /Confirm/i }));

    await waitFor(() =>
      expect(mockApi.setAdminFeatureFlag).toHaveBeenCalledWith("connectors", {
        enabled: false,
        reason: "Maintenance window",
      }),
    );
    expect(screen.queryByRole("button", { name: /Confirm/i })).toBeNull();
  });

  it("closes modal on Cancel without calling API", async () => {
    mockApi.listAdminFeatureFlags.mockResolvedValue(mockFlagsResponse);
    const user = userEvent.setup();
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Connectors")).toBeInTheDocument(),
    );

    const disableButtons = screen.getAllByRole("button", {
      name: /^Disable$/i,
    });
    await user.click(disableButtons[0]);
    await user.click(screen.getByRole("button", { name: /Cancel/i }));

    expect(mockApi.setAdminFeatureFlag).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /Confirm/i })).toBeNull();
  });

  it("calls clearAdminFeatureFlag when Reset to default is clicked", async () => {
    mockApi.listAdminFeatureFlags.mockResolvedValue(mockFlagsResponse);
    mockApi.clearAdminFeatureFlag.mockResolvedValue({
      organization_id: "org-1",
      flag_name: "evaluations",
      reverted_to_env_default: true,
      env_default: true,
    });
    const user = userEvent.setup();
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Evaluations")).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: /Reset to default/i }));

    await waitFor(() =>
      expect(mockApi.clearAdminFeatureFlag).toHaveBeenCalledWith("evaluations"),
    );
  });
});
