import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SettingsPage } from "@/components/settings/SettingsPage";
import type { SessionState } from "@/lib/auth-session";
import type { SettingsPreferences } from "@/lib/settings-preferences";

const mockState = vi.hoisted(() => ({
  authState: { status: "authenticated", session: null } as SessionState,
}));

const mockPreferencesApi = vi.hoisted(() => ({
  loadSettingsPreferences: vi.fn(),
  persistSettingsPreferences: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/settings-preferences", async () => {
  const actual = await vi.importActual<typeof import("@/lib/settings-preferences")>(
    "@/lib/settings-preferences",
  );

  return {
    ...actual,
    loadSettingsPreferences: () => mockPreferencesApi.loadSettingsPreferences(),
    persistSettingsPreferences: (preferences: SettingsPreferences) =>
      mockPreferencesApi.persistSettingsPreferences(preferences),
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
      <SettingsPage />
    </QueryClientProvider>,
  );
}

describe("SettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();

    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "user-1",
        email: "member@example.com",
        role: "member",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-1",
        refreshToken: "refresh-1",
      },
    };

    mockPreferencesApi.loadSettingsPreferences.mockResolvedValue({
      defaultTopK: 5,
      rerankEnabled: true,
      developerMode: false,
      notifications: {
        productUpdates: true,
        securityAlerts: true,
        documentProcessing: true,
      },
    } satisfies SettingsPreferences);

    mockPreferencesApi.persistSettingsPreferences.mockResolvedValue({
      preferences: {
        defaultTopK: 7,
        rerankEnabled: false,
        developerMode: true,
        notifications: {
          productUpdates: false,
          securityAlerts: true,
          documentProcessing: false,
        },
      },
      persistenceScope: "remote",
    });
  });

  it("renders profile, organization, security, and preferences sections", async () => {
    renderPage();

    expect(await screen.findByText("Profile, organization, and preferences")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Profile section" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Organization section" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Security section" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Preferences section" })).toBeInTheDocument();
  });

  it("validates preference values and blocks save on invalid top-k", async () => {
    renderPage();
    const input = await screen.findByLabelText(/default top-k/i);

    await userEvent.clear(input);
    await userEvent.type(input, "9999");
    await userEvent.click(screen.getByRole("button", { name: "Save preferences" }));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(mockPreferencesApi.persistSettingsPreferences).not.toHaveBeenCalled();
  });

  it("supports save and discard flow for unsaved preferences", async () => {
    renderPage();
    const input = await screen.findByLabelText(/default top-k/i);

    await userEvent.clear(input);
    await userEvent.type(input, "7");
    await userEvent.click(screen.getByLabelText("Enable rerank by default for new chat queries"));
    await userEvent.click(screen.getByRole("button", { name: "Save preferences" }));

    await waitFor(() => {
      expect(mockPreferencesApi.persistSettingsPreferences).toHaveBeenCalledTimes(1);
    });
    expect(await screen.findByText("Preferences saved successfully.")).toBeInTheDocument();

    await userEvent.clear(input);
    await userEvent.type(input, "6");
    await userEvent.click(screen.getByRole("button", { name: "Discard changes" }));

    expect(await screen.findByText("Unsaved changes were discarded.")).toBeInTheDocument();
    expect((screen.getByLabelText(/default top-k/i) as HTMLInputElement).value).toBe("7");
  });

  it("renders permission-aware admin-only section for non-admin users", async () => {
    renderPage();
    await screen.findByText("Admin-only controls");

    expect(screen.getByText("Admin controls restricted")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open admin surface" })).not.toBeInTheDocument();
  });

  it("shows admin controls for admin role", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "user-2",
        email: "admin@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-2",
        refreshToken: "refresh-2",
      },
    };

    renderPage();

    await screen.findByText("Admin-only controls");
    expect(screen.getByRole("link", { name: "Open admin surface" })).toBeInTheDocument();
    expect(screen.queryByText("Admin controls restricted")).not.toBeInTheDocument();
  });
});
