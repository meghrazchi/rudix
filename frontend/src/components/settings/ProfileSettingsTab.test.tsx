import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  const actual = await vi.importActual<typeof import("@/lib/schemas/settings")>(
    "@/lib/schemas/settings",
  );

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
    expect(
      screen.getByDisplayValue("alex.jones@example.com"),
    ).toBeInTheDocument();
    expect(screen.getByText("user-123")).toBeInTheDocument();
    expect(screen.getByText("member")).toBeInTheDocument();
  });

  it("shows initials avatar derived from email", async () => {
    renderTab();

    const avatar = await screen.findByLabelText("User initials avatar");
    expect(avatar).toBeInTheDocument();
    expect(avatar.textContent).toBe("AJ");
  });

  it("shows email input in account identity", async () => {
    renderTab();

    await screen.findByRole("region", { name: "Account identity section" });
    expect(
      screen.getByDisplayValue("alex.jones@example.com"),
    ).toBeInTheDocument();
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
    await screen.findByRole("button", { name: "Copy ID" });

    await userEvent.click(screen.getByRole("button", { name: "Copy ID" }));

    expect(writeText).toHaveBeenCalledWith("user-123");
    expect(await screen.findByText("Copied!")).toBeInTheDocument();
  });

  it("shows account identity section when session fields are null", async () => {
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

    expect(
      await screen.findByRole("region", { name: "Account identity section" }),
    ).toBeInTheDocument();
    expect(screen.getAllByDisplayValue("").length).toBeGreaterThan(0);
  });

  // ── Personal Preferences ──────────────────────────────────────────────────

  it("renders personal preferences section with form controls", async () => {
    renderTab();

    expect(
      await screen.findByRole("region", {
        name: "Personal preferences section",
      }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Display Language")).toBeInTheDocument();
    expect(screen.getByLabelText("Timezone")).toBeInTheDocument();
  });

  it("saves personal preferences to local storage", async () => {
    renderTab();

    const langSelect = await screen.findByLabelText("Display Language");
    await userEvent.selectOptions(langSelect, "de");

    await userEvent.click(
      screen.getByRole("button", { name: "Update Profile" }),
    );

    expect(mockSchemas.saveProfileUiPreferences).toHaveBeenCalledTimes(1);
    expect(
      await screen.findByText("Profile settings saved successfully."),
    ).toBeInTheDocument();
  });

  it("discards personal preference changes", async () => {
    renderTab();

    const langSelect = await screen.findByLabelText("Display Language");
    await userEvent.selectOptions(langSelect, "fr");

    const discardBtn = screen.getByRole("button", { name: "Discard Changes" });
    expect(discardBtn).not.toBeDisabled();

    await userEvent.click(discardBtn);

    expect(mockSchemas.saveProfileUiPreferences).not.toHaveBeenCalled();
    // After discard, language should be reset to original value
    expect(
      (screen.getByLabelText("Display Language") as HTMLSelectElement).value,
    ).toBe("en");
  });

  // ── AI / RAG Defaults ─────────────────────────────────────────────────────

  it("renders AI/RAG defaults section after preferences load", async () => {
    renderTab();

    expect(
      await screen.findByRole("region", {
        name: "AI and retrieval defaults section",
      }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Top-K Retrieval")).toBeInTheDocument();
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

  it("saves RAG preferences via Update Profile button", async () => {
    renderTab();

    await screen.findByRole("region", { name: "AI and retrieval defaults section" });

    await userEvent.click(
      screen.getByRole("button", { name: "Update Profile" }),
    );

    await waitFor(() => {
      expect(
        mockPreferencesApi.persistSettingsPreferences,
      ).toHaveBeenCalledTimes(1);
    });
    expect(
      await screen.findByText("Profile settings saved successfully."),
    ).toBeInTheDocument();
  });

  it("saves RAG preferences successfully", async () => {
    renderTab();

    const slider = await screen.findByLabelText("Top-K Retrieval");
    fireEvent.change(slider, { target: { value: "7" } });

    await userEvent.click(
      screen.getByRole("button", { name: "Update Profile" }),
    );

    await waitFor(() => {
      expect(
        mockPreferencesApi.persistSettingsPreferences,
      ).toHaveBeenCalledTimes(1);
    });
    expect(
      await screen.findByText("Profile settings saved successfully."),
    ).toBeInTheDocument();
  });

  it("discards RAG preference changes", async () => {
    renderTab();

    const slider = await screen.findByLabelText("Top-K Retrieval");
    fireEvent.change(slider, { target: { value: "3" } });
    expect((slider as HTMLInputElement).value).toBe("3");

    const discardBtn = screen.getByRole("button", { name: "Discard Changes" });
    expect(discardBtn).not.toBeDisabled();
    await userEvent.click(discardBtn);

    expect(
      (screen.getByLabelText("Top-K Retrieval") as HTMLInputElement).value,
    ).toBe("5");
  });

  // ── Notifications ─────────────────────────────────────────────────────────

  it("renders notifications section with notification types", async () => {
    renderTab();

    await screen.findByRole("region", { name: "Notifications section" });
    expect(screen.getByText("Processing Alerts")).toBeInTheDocument();
    expect(screen.getByText("Security Warnings")).toBeInTheDocument();
    expect(screen.getByText("Daily Evaluation Reports")).toBeInTheDocument();
  });

  it("defaults security warnings and processing alerts to on", async () => {
    renderTab();

    await screen.findByRole("region", { name: "Notifications section" });

    const securityWarningsCheckbox = screen
      .getAllByRole("checkbox")
      .find((cb) =>
        cb.closest("label")?.textContent?.includes("Security Warnings"),
      );
    const processingAlertsCheckbox = screen
      .getAllByRole("checkbox")
      .find((cb) =>
        cb.closest("label")?.textContent?.includes("Processing Alerts"),
      );

    expect(securityWarningsCheckbox).toBeChecked();
    expect(processingAlertsCheckbox).toBeChecked();
  });

  it("renders notification checkboxes inside the notifications section", async () => {
    renderTab();
    const section = await screen.findByRole("region", {
      name: "Notifications section",
    });

    const checkboxes = within(section).getAllByRole("checkbox");
    expect(checkboxes.length).toBeGreaterThan(0);
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
      screen.queryByRole("button", { name: "Sign out everywhere" }),
    ).not.toBeInTheDocument();
    expect(screen.getAllByText("Unavailable").length).toBeGreaterThan(0);
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
      screen.queryByRole("button", { name: "Delete account" }),
    ).not.toBeInTheDocument();
    expect(screen.getAllByText("Unavailable").length).toBeGreaterThan(0);
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
