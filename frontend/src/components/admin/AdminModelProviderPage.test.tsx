import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminModelProviderPage } from "@/components/admin/AdminModelProviderPage";
import type { SessionState } from "@/lib/auth-session";

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  getEffectiveModelProviderPolicy: vi.fn(),
  getModelProviderSettings: vi.fn(),
  updateModelProviderSettings: vi.fn(),
  resetModelProviderSettings: vi.fn(),
  listModelProviderChangeLog: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/model-provider-settings", () => ({
  getEffectiveModelProviderPolicy: () =>
    mockApi.getEffectiveModelProviderPolicy(),
  getModelProviderSettings: () => mockApi.getModelProviderSettings(),
  updateModelProviderSettings: (payload: unknown) =>
    mockApi.updateModelProviderSettings(payload),
  resetModelProviderSettings: (note: unknown) =>
    mockApi.resetModelProviderSettings(note),
  listModelProviderChangeLog: (params: unknown) =>
    mockApi.listModelProviderChangeLog(params),
}));

const SYSTEM_DEFAULT_POLICY = {
  organization_id: "org-1",
  provider: "openai",
  llm_model: "gpt-4o",
  embedding_model: "text-embedding-3-small",
  max_tokens: null,
  timeout_seconds: 30,
  max_retries: 2,
  fallback_model: null,
  disabled_models: [],
  llm_key_configured: true,
  source: "system_default" as const,
  version: 0,
};

const ORG_OVERRIDE_SETTINGS = {
  organization_id: "org-1",
  provider: "openai",
  llm_model: "gpt-4o-mini",
  embedding_model: "text-embedding-3-small",
  max_tokens: 4096,
  timeout_seconds: 30,
  max_retries: 3,
  fallback_model: "gpt-3.5-turbo",
  disabled_models: ["davinci"],
  llm_key_configured: true,
  version: 2,
  updated_by_id: null,
  updated_at: "2026-06-05T00:00:00Z",
};

const EMPTY_CHANGE_LOG = { items: [], total: 0 };

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AdminModelProviderPage />
    </QueryClientProvider>,
  );
}

describe("AdminModelProviderPage", () => {
  beforeEach(() => {
    Object.values(mockApi).forEach((fn) => fn.mockReset());
    mockApi.getEffectiveModelProviderPolicy.mockResolvedValue(
      SYSTEM_DEFAULT_POLICY,
    );
    mockApi.getModelProviderSettings.mockRejectedValue({ status: 404 });
    mockApi.listModelProviderChangeLog.mockResolvedValue(EMPTY_CHANGE_LOG);
    mockState.authState = {
      status: "authenticated",
      session: { role: "admin", userId: "u1", organizationId: "org-1" },
    } as unknown as SessionState;
  });

  it("shows forbidden state for non-admin user", async () => {
    mockState.authState = {
      status: "authenticated",
      session: { role: "member", userId: "u2", organizationId: "org-1" },
    } as unknown as SessionState;

    renderPage();
    expect(
      screen.getByText(/Model provider settings restricted/i),
    ).toBeTruthy();
  });

  it("renders page heading for admin", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Model provider settings")).toBeTruthy(),
    );
  });

  it("shows system_default badge when no org settings exist", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("System default")).toBeTruthy(),
    );
  });

  it("shows org_override badge when org settings exist", async () => {
    mockApi.getEffectiveModelProviderPolicy.mockResolvedValue({
      ...SYSTEM_DEFAULT_POLICY,
      source: "org_override",
      version: 2,
      llm_model: "gpt-4o-mini",
    });
    mockApi.getModelProviderSettings.mockResolvedValue(ORG_OVERRIDE_SETTINGS);

    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Org override")).toBeTruthy(),
    );
  });

  it("shows create button when no org settings exist", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Create org overrides")).toBeTruthy(),
    );
  });

  it("shows edit and reset buttons when org settings exist", async () => {
    mockApi.getModelProviderSettings.mockResolvedValue(ORG_OVERRIDE_SETTINGS);

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Edit org overrides")).toBeTruthy();
      expect(screen.getByText("Reset to system defaults")).toBeTruthy();
    });
  });

  it("opens editor when create button is clicked", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Create org overrides")).toBeTruthy(),
    );
    fireEvent.click(screen.getByText("Create org overrides"));
    expect(screen.getByPlaceholderText("gpt-4o")).toBeTruthy();
    expect(screen.getByPlaceholderText("openai")).toBeTruthy();
  });

  it("calls updateModelProviderSettings on save", async () => {
    mockApi.updateModelProviderSettings.mockResolvedValue({
      ...ORG_OVERRIDE_SETTINGS,
      version: 1,
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Create org overrides")).toBeTruthy(),
    );

    fireEvent.click(screen.getByText("Create org overrides"));

    const llmInput = screen.getByPlaceholderText("gpt-4o");
    fireEvent.change(llmInput, { target: { value: "gpt-4o-mini" } });

    fireEvent.click(screen.getByText("Save settings"));
    await waitFor(() =>
      expect(mockApi.updateModelProviderSettings).toHaveBeenCalledWith(
        expect.objectContaining({ llm_model: "gpt-4o-mini" }),
      ),
    );
  });

  it("shows warning when llm_key_configured is false", async () => {
    mockApi.getEffectiveModelProviderPolicy.mockResolvedValue({
      ...SYSTEM_DEFAULT_POLICY,
      llm_key_configured: false,
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/No LLM API key is set/i)).toBeTruthy(),
    );
  });

  it("shows reset confirmation dialog when reset button clicked", async () => {
    mockApi.getModelProviderSettings.mockResolvedValue(ORG_OVERRIDE_SETTINGS);
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Reset to system defaults")).toBeTruthy(),
    );

    fireEvent.click(screen.getByText("Reset to system defaults"));
    expect(screen.getByText("Reset to system defaults?")).toBeTruthy();
    expect(screen.getByText("Confirm reset")).toBeTruthy();
  });

  it("calls resetModelProviderSettings on confirm reset", async () => {
    mockApi.getModelProviderSettings.mockResolvedValue(ORG_OVERRIDE_SETTINGS);
    mockApi.resetModelProviderSettings.mockResolvedValue(undefined);

    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Reset to system defaults")).toBeTruthy(),
    );
    fireEvent.click(screen.getByText("Reset to system defaults"));
    fireEvent.click(screen.getByText("Confirm reset"));

    await waitFor(() =>
      expect(mockApi.resetModelProviderSettings).toHaveBeenCalled(),
    );
  });

  it("renders change log entries when present", async () => {
    mockApi.listModelProviderChangeLog.mockResolvedValue({
      items: [
        {
          entry_id: "00000000-0000-0000-0000-000000000001",
          organization_id: "org-1",
          version_number: 2,
          settings_snapshot: { llm_model: "gpt-4o-mini" },
          change_note: "Switched to mini",
          changed_by_id: null,
          created_at: "2026-06-05T12:00:00Z",
        },
      ],
      total: 1,
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Switched to mini")).toBeTruthy(),
    );
    expect(screen.getByText("v2")).toBeTruthy();
  });

  it("never renders raw API key strings in the DOM", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Model provider settings")).toBeTruthy(),
    );
    const domText = document.body.innerHTML;
    expect(domText).not.toContain("sk-");
    expect(domText).not.toContain("openai_api_key");
  });
});
