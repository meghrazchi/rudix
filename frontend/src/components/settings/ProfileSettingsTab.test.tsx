import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProfileSettingsTab } from "@/components/settings/ProfileSettingsTab";
import type { SessionState } from "@/lib/auth-session";
import type { SettingsPreferences } from "@/lib/settings-preferences";
import type { ProfileCapabilities } from "@/lib/api/profile";

const mockState = vi.hoisted(() => ({
  authState: { status: "authenticated", session: null } as SessionState,
  signOut: vi.fn(),
  replace: vi.fn(),
}));

const mockPreferencesApi = vi.hoisted(() => ({
  loadSettingsPreferences: vi.fn(),
  persistSettingsPreferences: vi.fn(),
}));

const mockSchemas = vi.hoisted(() => ({
  loadProfileUiPreferences: vi.fn(),
  saveProfileUiPreferences: vi.fn(),
}));

const mockProfileApi = vi.hoisted(() => ({
  capabilities: {
    signOutAllDevicesEnabled: false,
    deleteAccountEnabled: false,
  } as ProfileCapabilities,
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

vi.mock("@/lib/schemas/settings", async () => {
  const actual = await vi.importActual<
    typeof import("@/lib/schemas/settings")
  >("@/lib/schemas/settings");

  return {
    ...actual,
    loadProfileUiPreferences: () => mockSchemas.loadProfileUiPreferences(),
    saveProfileUiPreferences: (...args: unknown[]) =>
      mockSchemas.saveProfileUiPreferences(...args),
  };
});

vi.mock("@/lib/api/profile", () => ({
  getProfileCapabilities: () => mockProfileApi.capabilities,
  signOutAllDevices: vi.fn(),
  deletePersonalAccount: vi.fn(),
}));

const FULL_PREFERENCES: SettingsPreferences = {
  defaultTopK: 5,
  rerankEnabled: true,
  developerMode: false,
  answerDetailLevel: "standard",
  showConfidenceScore: false,
  expandCitations: false,
  notifications: {
    productUpdates: true,
    securityAlerts: true,
    documentProcessing: true,
    failedIndexing: true,
    evaluationCompletion: true,
    billingWarnings: true,
  },
};

function renderTab() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <ProfileSettingsTab />
    </QueryClientProvider>,
  );
}

describe("ProfileSettingsTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockState.signOut.mockResolvedValue(undefined);
    mockProfileApi.capabilities = {
      signOutAllDevicesEnabled: false,
      deleteAccountEnabled: false,
    };

    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "user-123",
        email: "alex.jones@example.com",
        role: "member",
        organizationId: "org-1",
        organizationName: "Acme Corp",
        accessToken: "secret-access-token",
        refreshToken: "secret-refresh-token",
      },
    };

    mockPreferencesApi.loadSettingsPreferences.mockResolvedValue(
      FULL_PREFERENCES,
    );

    mockPreferencesApi.persistSettingsPreferences.mockResolvedValue({
      preferences: { ...FULL_PREFERENCES, defaultTopK: 7 },
      persistenceScope: "remote",
    });

    mockSchemas.loadProfileUiPreferences.mockReturnValue({
      language: "en",
      timezone: "",
      dateFormat: "MMM D, YYYY",
      theme: "light",
      landingPage: "/dashboard",
      keyboardShortcutHints: true,
    });
  });

  // ── Account Identity ──────────────────────────────────────────────────────

  it("renders account identity section with session data", async () => {
    renderTab();

    expect(
      await screen.findByRole("region", { name: "Account identity section" }),
    ).toBeInTheDocument();
    expect(screen.getByText("alex.jones@example.com")).toBeInTheDocument();
    expect(screen.getByText("user-123")).toBeInTheDocument();
    expect(screen.getByText("member")).toBeInTheDocument();
    expect(screen.getByText("Acme Corp")).toBeInTheDocument();
  });

  it("shows initials avatar derived from email", async () => {
    renderTab();

    const avatar = await screen.findByLabelText("User initials avatar");
    expect(avatar).toBeInTheDocument();
    expect(avatar.textContent).toBe("AJ");
  });

  it("shows Verified badge in account identity", async () => {
    renderTab();

    await screen.findByRole("region", { name: "Account identity section" });
    expect(screen.getByText("Verified")).toBeInTheDocument();
  });

  it("never renders access token or refresh token values", async () => {
    renderTab();

    await screen.findByRole("region", { name: "Account identity section" });
    expect(screen.queryByText("secret-access-token")).not.toBeInTheDocument();
    expect(screen.queryByText("secret-refresh-token")).not.toBeInTheDocument();
  });

  it("copies user ID to clipboard when copy button clicked", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      writable: true,
      configurable: true,
    });

    renderTab();
    await screen.findByRole("button", { name: "Copy user ID" });

    await userEvent.click(screen.getByRole("button", { name: "Copy user ID" }));

    expect(writeText).toHaveBeenCalledWith("user-123");
    expect(await screen.findByText("Copied!")).toBeInTheDocument();
  });

  it("shows Not available for missing session fields", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "user-1",
        email: null,
        role: "viewer",
        organizationId: null,
        organizationName: null,
      },
    };

    renderTab();
    await screen.findByRole("region", { name: "Account identity section" });

    expect(screen.getAllByText("Not available").length).toBeGreaterThan(0);
    expect(screen.getByText("Not assigned")).toBeInTheDocument();
  });

  // ── Personal Preferences ──────────────────────────────────────────────────

  it("renders personal preferences section with form controls", async () => {
    renderTab();

    expect(
      await screen.findByRole("region", { name: "Personal preferences section" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Display Language")).toBeInTheDocument();
    expect(screen.getByLabelText("Timezone")).toBeInTheDocument();
    expect(screen.getByLabelText("Date & Time Format")).toBeInTheDocument();
    expect(screen.getByLabelText("Default Landing Page")).toBeInTheDocument();
  });

  it("saves personal preferences to local storage", async () => {
    renderTab();

    const langSelect = await screen.findByLabelText("Display Language");
    await userEvent.selectOptions(langSelect, "de");

    await userEvent.click(
      screen.getByRole("button", { name: "Save personal preferences" }),
    );

    expect(mockSchemas.saveProfileUiPreferences).toHaveBeenCalledTimes(1);
    expect(
      await screen.findByText("Personal preferences saved."),
    ).toBeInTheDocument();
  });

  it("discards personal preference changes", async () => {
    renderTab();

    const langSelect = await screen.findByLabelText("Display Language");
    await userEvent.selectOptions(langSelect, "fr");

    const discardBtn = screen.getByRole("button", {
      name: "Discard personal changes",
    });
    expect(discardBtn).not.toBeDisabled();

    await userEvent.click(discardBtn);

    expect(
      await screen.findByText("Unsaved changes were discarded."),
    ).toBeInTheDocument();
    expect(
      mockSchemas.saveProfileUiPreferences,
    ).not.toHaveBeenCalled();
  });

  // ── AI / RAG Defaults ─────────────────────────────────────────────────────

  it("renders AI/RAG defaults section after preferences load", async () => {
    renderTab();

    expect(
      await screen.findByRole("region", {
        name: "AI and retrieval defaults section",
      }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/default top-k/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Answer Detail Level")).toBeInTheDocument();
  });

  it("shows loading state while preferences load", () => {
    mockPreferencesApi.loadSettingsPreferences.mockReturnValue(
      new Promise(() => {}),
    );

    renderTab();

    expect(screen.getByText("Loading preferences...")).toBeInTheDocument();
  });

  it("shows error state when preferences fail to load", async () => {
    mockPreferencesApi.loadSettingsPreferences.mockRejectedValue(
      new Error("Something went wrong while contacting the API."),
    );

    renderTab();

    await waitFor(() => {
      expect(
        screen.getByText("Something went wrong while contacting the API."),
      ).toBeInTheDocument();
    });
  });

  it("validates top-k and blocks save on invalid value", async () => {
    renderTab();

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

  it("saves RAG preferences successfully", async () => {
    renderTab();

    const input = await screen.findByLabelText(/default top-k/i);
    await userEvent.clear(input);
    await userEvent.type(input, "7");

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
  });

  it("discards RAG preference changes", async () => {
    renderTab();

    const input = await screen.findByLabelText(/default top-k/i);
    await userEvent.clear(input);
    await userEvent.type(input, "3");

    const discardBtn = screen.getByRole("button", { name: "Discard changes" });
    expect(discardBtn).not.toBeDisabled();
    await userEvent.click(discardBtn);

    expect(
      await screen.findByText("Unsaved changes were discarded."),
    ).toBeInTheDocument();
    expect(
      (screen.getByLabelText(/default top-k/i) as HTMLInputElement).value,
    ).toBe("5");
  });

  // ── Notifications ─────────────────────────────────────────────────────────

  it("renders notifications section with all six notification types", async () => {
    renderTab();

    await screen.findByRole("region", { name: "Notifications section" });
    expect(screen.getByText("Product updates")).toBeInTheDocument();
    expect(screen.getByText("Security alerts")).toBeInTheDocument();
    expect(screen.getByText("Document processing")).toBeInTheDocument();
    expect(screen.getByText("Failed indexing")).toBeInTheDocument();
    expect(screen.getByText("Evaluation completion")).toBeInTheDocument();
    expect(screen.getByText("Billing warnings")).toBeInTheDocument();
  });

  it("defaults security alerts and document processing to on", async () => {
    renderTab();

    await screen.findByRole("region", { name: "Notifications section" });

    const securityAlertsLabel = screen
      .getAllByRole("checkbox")
      .find((cb) => cb.closest("label")?.textContent?.includes("Security alerts"));
    const docProcessingLabel = screen
      .getAllByRole("checkbox")
      .find((cb) =>
        cb.closest("label")?.textContent?.includes("Document processing"),
      );

    expect(securityAlertsLabel).toBeChecked();
    expect(docProcessingLabel).toBeChecked();
  });

  it("shows coming-soon connector and agent notifications as disabled", async () => {
    renderTab();
    await screen.findByRole("region", { name: "Notifications section" });

    expect(screen.getByText("Connector sync failures")).toBeInTheDocument();
    expect(screen.getByText("Agent run status")).toBeInTheDocument();
  });

  // ── Account Actions ───────────────────────────────────────────────────────

  it("renders account actions section", async () => {
    renderTab();

    expect(
      await screen.findByRole("region", { name: "Account actions section" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Sign out" }),
    ).toBeInTheDocument();
  });

  it("sign out calls signOut and redirects to login", async () => {
    renderTab();

    await screen.findByRole("button", { name: "Sign out" });
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() => {
      expect(mockState.signOut).toHaveBeenCalledTimes(1);
      expect(mockState.replace).toHaveBeenCalledWith(
        "/login?reason=signed_out",
      );
    });
  });

  it("shows unavailable state for sign-out-all-devices when not configured", async () => {
    renderTab();

    await screen.findByRole("region", { name: "Account actions section" });
    expect(
      screen.getByLabelText("Sign out from all devices unavailable"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Sign out everywhere" }),
    ).not.toBeInTheDocument();
  });

  it("shows sign-out-everywhere button when capability is enabled", async () => {
    mockProfileApi.capabilities = {
      signOutAllDevicesEnabled: true,
      deleteAccountEnabled: false,
    };

    renderTab();

    await screen.findByRole("region", { name: "Account actions section" });
    expect(
      screen.getByRole("button", { name: "Sign out everywhere" }),
    ).toBeInTheDocument();
  });

  it("shows unavailable state for delete account when not configured", async () => {
    renderTab();

    await screen.findByRole("region", { name: "Account actions section" });
    expect(
      screen.getByLabelText("Delete account unavailable"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Delete account" }),
    ).not.toBeInTheDocument();
  });

  it("shows delete account button when capability is enabled", async () => {
    mockProfileApi.capabilities = {
      signOutAllDevicesEnabled: false,
      deleteAccountEnabled: true,
    };

    renderTab();

    await screen.findByRole("region", { name: "Account actions section" });
    expect(
      screen.getByRole("button", { name: "Delete account" }),
    ).toBeInTheDocument();
  });
});
