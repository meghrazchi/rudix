import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SettingsPage } from "@/components/settings/SettingsPage";
import type { SessionState } from "@/lib/auth-session";
import type { SettingsPreferences } from "@/lib/settings-preferences";
import type { TeamCapabilities } from "@/lib/api/team";

const mockState = vi.hoisted(() => ({
  authState: { status: "authenticated", session: null } as SessionState,
  signOut: vi.fn(),
  replace: vi.fn(),
  tab: null as string | null,
}));

const mockPreferencesApi = vi.hoisted(() => ({
  loadSettingsPreferences: vi.fn(),
  persistSettingsPreferences: vi.fn(),
}));

const mockTeamApi = vi.hoisted(() => ({
  capabilities: {
    listMembersEnabled: false,
    inviteEnabled: false,
    updateRoleEnabled: false,
    removeMemberEnabled: false,
  } satisfies TeamCapabilities,
  listTeamMembers: vi.fn(),
  inviteTeamMember: vi.fn(),
  updateTeamMemberRole: vi.fn(),
  removeTeamMember: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: mockState.signOut,
  }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    replace: mockState.replace,
  }),
  useSearchParams: () => ({
    get: (key: string) => (key === "tab" ? mockState.tab : null),
  }),
}));

vi.mock("@/lib/settings-preferences", async () => {
  const actual = await vi.importActual<
    typeof import("@/lib/settings-preferences")
  >("@/lib/settings-preferences");

  return {
    ...actual,
    loadSettingsPreferences: () => mockPreferencesApi.loadSettingsPreferences(),
    persistSettingsPreferences: (preferences: SettingsPreferences) =>
      mockPreferencesApi.persistSettingsPreferences(preferences),
  };
});

vi.mock("@/lib/api/team", () => ({
  getTeamCapabilities: () => mockTeamApi.capabilities,
  listTeamMembers: (...args: unknown[]) => mockTeamApi.listTeamMembers(...args),
  inviteTeamMember: (...args: unknown[]) =>
    mockTeamApi.inviteTeamMember(...args),
  updateTeamMemberRole: (...args: unknown[]) =>
    mockTeamApi.updateTeamMemberRole(...args),
  removeTeamMember: (...args: unknown[]) =>
    mockTeamApi.removeTeamMember(...args),
  isTeamEndpointUnavailableError: () => false,
}));

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
    mockState.tab = null;
    mockState.signOut.mockResolvedValue(undefined);
    mockTeamApi.capabilities = {
      listMembersEnabled: false,
      inviteEnabled: false,
      updateRoleEnabled: false,
      removeMemberEnabled: false,
    };

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

  it("renders tab navigation with all four tabs", () => {
    renderPage();

    expect(
      screen.getByRole("tablist", { name: "Settings navigation" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Profile" })).toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: "Organization" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Security" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Billing" })).toBeInTheDocument();
  });

  it("defaults to the Profile tab when no tab param is set", async () => {
    renderPage();

    expect(
      screen.getByRole("tab", { name: "Profile" }),
    ).toHaveAttribute("aria-selected", "true");
    expect(
      await screen.findByRole("region", { name: "Profile section" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Preferences section" }),
    ).toBeInTheDocument();
  });

  it("shows Profile tab content at ?tab=profile", async () => {
    mockState.tab = "profile";
    renderPage();

    expect(
      await screen.findByRole("region", { name: "Profile section" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Preferences section" }),
    ).toBeInTheDocument();
  });

  it("shows Organization tab content at ?tab=organization", async () => {
    mockState.tab = "organization";
    renderPage();

    expect(
      await screen.findByRole("region", { name: "Organization section" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Team management section" }),
    ).toBeInTheDocument();
  });

  it("shows Security tab content at ?tab=security", async () => {
    mockState.tab = "security";
    renderPage();

    expect(
      await screen.findByRole("region", { name: "Security section" }),
    ).toBeInTheDocument();
  });

  it("shows Billing tab content at ?tab=billing", async () => {
    mockState.tab = "billing";
    renderPage();

    expect(
      await screen.findByRole("region", { name: "Billing and usage section" }),
    ).toBeInTheDocument();
  });

  it("falls back to Profile tab for invalid tab param", async () => {
    mockState.tab = "invalid-tab-value";
    renderPage();

    expect(
      await screen.findByRole("region", { name: "Profile section" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: "Profile" }),
    ).toHaveAttribute("aria-selected", "true");
  });

  it("navigates to the clicked tab by updating the URL", async () => {
    renderPage();

    await userEvent.click(screen.getByRole("tab", { name: "Security" }));

    expect(mockState.replace).toHaveBeenCalledWith(
      "/settings?tab=security",
      expect.objectContaining({ scroll: false }),
    );
  });

  it("validates preference values and blocks save on invalid top-k", async () => {
    renderPage();
    const input = await screen.findByLabelText(/default top-k/i);

    await userEvent.clear(input);
    await userEvent.type(input, "9999");
    await userEvent.click(
      screen.getByRole("button", { name: "Save preferences" }),
    );

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      mockPreferencesApi.persistSettingsPreferences,
    ).not.toHaveBeenCalled();
  });

  it("supports save and discard flow for unsaved preferences", async () => {
    renderPage();
    const input = await screen.findByLabelText(/default top-k/i);

    await userEvent.clear(input);
    await userEvent.type(input, "7");
    await userEvent.click(
      screen.getByLabelText("Enable rerank by default for new chat queries"),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Save preferences" }),
    );

    await waitFor(() => {
      expect(
        mockPreferencesApi.persistSettingsPreferences,
      ).toHaveBeenCalledTimes(1);
    });
    expect(
      await screen.findByText("Preferences saved successfully."),
    ).toBeInTheDocument();

    await userEvent.clear(input);
    await userEvent.type(input, "6");
    await userEvent.click(
      screen.getByRole("button", { name: "Discard changes" }),
    );

    expect(
      await screen.findByText("Unsaved changes were discarded."),
    ).toBeInTheDocument();
    expect(
      (screen.getByLabelText(/default top-k/i) as HTMLInputElement).value,
    ).toBe("7");
  });

  it("renders permission-aware admin-only section for non-admin users", async () => {
    mockState.tab = "organization";
    renderPage();
    await screen.findByText("Admin-only controls");

    expect(screen.getByText("Admin controls restricted")).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Open admin surface" }),
    ).not.toBeInTheDocument();
  });

  it("shows admin controls for admin role", async () => {
    mockState.tab = "organization";
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
    expect(
      screen.getByRole("link", { name: "Open admin surface" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Admin controls restricted"),
    ).not.toBeInTheDocument();
  });

  it("uses the shared logout flow from settings security area", async () => {
    mockState.tab = "security";
    renderPage();
    await screen.findByRole("region", { name: "Security section" });

    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() => {
      expect(mockState.signOut).toHaveBeenCalledTimes(1);
      expect(mockState.replace).toHaveBeenCalledWith(
        "/login?reason=signed_out",
      );
    });
  });
});
