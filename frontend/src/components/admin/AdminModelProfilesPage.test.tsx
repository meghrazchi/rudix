import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminModelProfilesPage } from "@/components/admin/AdminModelProfilesPage";
import type { SessionState } from "@/lib/auth-session";
import type { EffectiveModelPolicyResponse, ModelProfileListResponse } from "@/lib/api/model-profiles";

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  listModelProfiles: vi.fn(),
  getEffectiveModelPolicy: vi.fn(),
  upsertModelProfile: vi.fn(),
  deleteModelProfile: vi.fn(),
  validateModelProfile: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/model-profiles", () => ({
  listModelProfiles: () => mockApi.listModelProfiles(),
  getEffectiveModelPolicy: () => mockApi.getEffectiveModelPolicy(),
  upsertModelProfile: (taskType: unknown, payload: unknown) =>
    mockApi.upsertModelProfile(taskType, payload),
  deleteModelProfile: (taskType: unknown) => mockApi.deleteModelProfile(taskType),
  validateModelProfile: (payload: unknown) => mockApi.validateModelProfile(payload),
}));

const ADMIN_SESSION: SessionState = {
  status: "authenticated",
  session: {
    userId: "u1",
    organizationId: "org-1",
    role: "admin",
    email: "admin@test.com",
  },
};

const EMPTY_LIST: ModelProfileListResponse = { items: [], total: 0 };

const EFFECTIVE_ALL_DEFAULTS: EffectiveModelPolicyResponse = {
  organization_id: "org-1",
  profiles: [
    { task_type: "chat", provider_type: "openai", base_model: "gpt-4o", max_tokens: null, temperature: null, json_mode: false, streaming: true, fallback_provider_key: null, source: "env_default", version: 0 },
    { task_type: "summarization", provider_type: "openai", base_model: "gpt-4o", max_tokens: null, temperature: null, json_mode: false, streaming: true, fallback_provider_key: null, source: "env_default", version: 0 },
    { task_type: "comparison", provider_type: "openai", base_model: "gpt-4o", max_tokens: null, temperature: null, json_mode: true, streaming: true, fallback_provider_key: null, source: "env_default", version: 0 },
    { task_type: "embeddings", provider_type: "openai", base_model: "text-embedding-3-small", max_tokens: null, temperature: null, json_mode: false, streaming: false, fallback_provider_key: null, source: "env_default", version: 0 },
    { task_type: "evaluations", provider_type: "openai", base_model: "gpt-4o", max_tokens: null, temperature: null, json_mode: true, streaming: false, fallback_provider_key: null, source: "env_default", version: 0 },
    { task_type: "agentic", provider_type: "openai", base_model: "gpt-4o", max_tokens: null, temperature: null, json_mode: false, streaming: true, fallback_provider_key: null, source: "env_default", version: 0 },
  ],
  feature_local_llm_enabled: false,
  feature_local_embeddings_enabled: false,
  feature_fallback_enabled: false,
  feature_request_override_enabled: false,
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
      <AdminModelProfilesPage />
    </QueryClientProvider>,
  );
}

describe("AdminModelProfilesPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockState.authState = ADMIN_SESSION;
    mockApi.listModelProfiles.mockResolvedValue(EMPTY_LIST);
    mockApi.getEffectiveModelPolicy.mockResolvedValue(EFFECTIVE_ALL_DEFAULTS);
    mockApi.validateModelProfile.mockResolvedValue({ valid: true, issues: [] });
  });

  it("shows forbidden state for unauthenticated users", () => {
    mockState.authState = { status: "unauthenticated", session: null };
    renderPage();
    expect(screen.getByText(/restricted/i)).toBeTruthy();
  });

  it("shows forbidden state for viewer role", () => {
    mockState.authState = {
      status: "authenticated",
      session: { userId: "u2", organizationId: "org-1", role: "viewer", email: "v@test.com" },
    };
    renderPage();
    expect(screen.getByText(/restricted/i)).toBeTruthy();
  });

  it("renders all six task type headings", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Chat")).toBeTruthy();
    });
    expect(screen.getByText("Summarization")).toBeTruthy();
    expect(screen.getByText("Comparison")).toBeTruthy();
    expect(screen.getByText("Embeddings")).toBeTruthy();
    expect(screen.getByText("Evaluations")).toBeTruthy();
    expect(screen.getByText("Agentic Workflows")).toBeTruthy();
  });

  it("shows 'env default' badges when no org profiles exist", async () => {
    renderPage();
    await waitFor(() => {
      const badges = screen.getAllByText("env default");
      expect(badges.length).toBe(6);
    });
  });

  it("shows 'org override' badge for a configured profile", async () => {
    const withOrgProfile: EffectiveModelPolicyResponse = {
      ...EFFECTIVE_ALL_DEFAULTS,
      profiles: EFFECTIVE_ALL_DEFAULTS.profiles.map((p) =>
        p.task_type === "chat" ? { ...p, source: "org_profile" } : p,
      ),
    };
    const listWithProfile: ModelProfileListResponse = {
      items: [
        {
          profile_id: "p1",
          organization_id: "org-1",
          profile_name: "Custom Chat",
          task_type: "chat",
          provider_type: "openai",
          base_model: "gpt-4o-mini",
          context_window: null,
          max_tokens: null,
          temperature: null,
          json_mode: false,
          streaming: true,
          fallback_provider_key: null,
          is_active: true,
          is_experimental: false,
          cost_metadata: {},
          version: 1,
          updated_by_id: null,
          created_at: "2026-06-09T00:00:00Z",
          updated_at: "2026-06-09T00:00:00Z",
        },
      ],
      total: 1,
    };
    mockApi.getEffectiveModelPolicy.mockResolvedValue(withOrgProfile);
    mockApi.listModelProfiles.mockResolvedValue(listWithProfile);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("org override")).toBeTruthy();
    });
  });

  it("shows loading state while queries are in flight", () => {
    mockApi.getEffectiveModelPolicy.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByText(/loading model profiles/i)).toBeTruthy();
  });

  it("shows error state when effective policy fails", async () => {
    mockApi.getEffectiveModelPolicy.mockRejectedValue(new Error("network error"));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/unable to load model profiles/i)).toBeTruthy();
    });
  });

  it("shows feature flags section", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/local llm/i)).toBeTruthy();
    });
    expect(screen.getByText(/provider fallback/i)).toBeTruthy();
  });

  it("shows enabled state for feature flags when true", async () => {
    mockApi.getEffectiveModelPolicy.mockResolvedValue({
      ...EFFECTIVE_ALL_DEFAULTS,
      feature_local_llm_enabled: true,
      feature_fallback_enabled: true,
    });
    renderPage();
    await waitFor(() => {
      const enabledItems = screen.getAllByText("enabled");
      expect(enabledItems.length).toBeGreaterThanOrEqual(2);
    });
  });

  it("calls upsertModelProfile on save after passing validation", async () => {
    mockApi.upsertModelProfile.mockResolvedValue({
      profile_id: "p1",
      organization_id: "org-1",
      profile_name: "Chat",
      task_type: "chat",
      provider_type: "openai",
      base_model: "gpt-4o",
      context_window: null,
      max_tokens: null,
      temperature: null,
      json_mode: false,
      streaming: true,
      fallback_provider_key: null,
      is_active: true,
      is_experimental: false,
      cost_metadata: {},
      version: 1,
      updated_by_id: null,
      created_at: "2026-06-09T00:00:00Z",
      updated_at: "2026-06-09T00:00:00Z",
    });
    renderPage();
    await waitFor(() => screen.getByText("Chat"));

    const modelInputs = screen.getAllByPlaceholderText(/gpt-4o|text-embedding/);
    fireEvent.change(modelInputs[0], { target: { value: "gpt-4o-mini" } });

    const saveButtons = screen.getAllByText("Create profile");
    fireEvent.click(saveButtons[0]);

    await waitFor(() => {
      expect(mockApi.validateModelProfile).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(mockApi.upsertModelProfile).toHaveBeenCalledWith(
        "chat",
        expect.objectContaining({ base_model: "gpt-4o-mini" }),
      );
    });
  });

  it("shows validation issues without calling upsert when validation fails", async () => {
    mockApi.validateModelProfile.mockResolvedValue({
      valid: false,
      issues: [{ field: "json_mode", code: "json_mode_required", message: "JSON mode required." }],
    });
    renderPage();
    await waitFor(() => screen.getByText("Evaluations"));

    const modelInputs = screen.getAllByPlaceholderText(/gpt-4o|text-embedding/);
    // find the evaluations editor — it's the 5th task type
    fireEvent.change(modelInputs[4], { target: { value: "gpt-4o" } });

    const saveButtons = screen.getAllByText("Create profile");
    fireEvent.click(saveButtons[4]);

    await waitFor(() => {
      expect(screen.getByText("JSON mode required.")).toBeTruthy();
    });
    expect(mockApi.upsertModelProfile).not.toHaveBeenCalled();
  });

  it("shows delete confirm flow and calls deleteModelProfile", async () => {
    const listWithProfile: ModelProfileListResponse = {
      items: [
        {
          profile_id: "p1",
          organization_id: "org-1",
          profile_name: "Chat",
          task_type: "chat",
          provider_type: "openai",
          base_model: "gpt-4o",
          context_window: null,
          max_tokens: null,
          temperature: null,
          json_mode: false,
          streaming: true,
          fallback_provider_key: null,
          is_active: true,
          is_experimental: false,
          cost_metadata: {},
          version: 1,
          updated_by_id: null,
          created_at: "2026-06-09T00:00:00Z",
          updated_at: "2026-06-09T00:00:00Z",
        },
      ],
      total: 1,
    };
    mockApi.listModelProfiles.mockResolvedValue(listWithProfile);
    mockApi.deleteModelProfile.mockResolvedValue(undefined);
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Remove override")).toBeTruthy();
    });
    fireEvent.click(screen.getByText("Remove override"));
    expect(screen.getByText("Revert to env default?")).toBeTruthy();

    fireEvent.click(screen.getByText("Confirm"));
    await waitFor(() => {
      expect(mockApi.deleteModelProfile).toHaveBeenCalledWith("chat");
    });
  });
});
