import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UserProfilePage } from "@/components/user/UserProfilePage";
import type { SessionState } from "@/lib/auth-session";
import type { SettingsPreferences } from "@/lib/settings-preferences";
import type { ProfileCapabilities } from "@/lib/api/profile";

const mockState = vi.hoisted(() => ({
  authState: { status: "authenticated", session: null } as SessionState,
  signOut: vi.fn(),
  replace: vi.fn(),
  refresh: vi.fn(),
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
    meEnabled: false,
    preferencesEnabled: false,
    signOutAllDevicesEnabled: false,
    deleteAccountEnabled: false,
    avatarEnabled: false,
    changePasswordEnabled: false,
  } as ProfileCapabilities,
  getMe: vi.fn(),
  updateMe: vi.fn(),
  uploadAvatar: vi.fn(),
  removeAvatar: vi.fn(),
  signOutAllDevices: vi.fn(),
  deletePersonalAccount: vi.fn(),
  changePassword: vi.fn(),
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
    refresh: mockState.refresh,
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
  getMe: () => mockProfileApi.getMe(),
  updateMe: (...args: unknown[]) => mockProfileApi.updateMe(...args),
  uploadAvatar: (...args: unknown[]) => mockProfileApi.uploadAvatar(...args),
  removeAvatar: () => mockProfileApi.removeAvatar(),
  signOutAllDevices: () => mockProfileApi.signOutAllDevices(),
  deletePersonalAccount: () => mockProfileApi.deletePersonalAccount(),
  changePassword: (...args: unknown[]) =>
    mockProfileApi.changePassword(...args),
}));

const FULL_PREFERENCES: SettingsPreferences = {
  defaultTopK: 5,
  confidenceThreshold: 70,
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
      <UserProfilePage />
    </QueryClientProvider>,
  );
}

describe("UserProfilePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockState.signOut.mockResolvedValue(undefined);
    mockProfileApi.capabilities = {
      meEnabled: false,
      preferencesEnabled: false,
      signOutAllDevicesEnabled: false,
      deleteAccountEnabled: false,
      avatarEnabled: false,
      changePasswordEnabled: false,
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

    mockProfileApi.getMe.mockResolvedValue({
      id: "user-123",
      email: "alex.jones@example.com",
      name: "Alex Jones",
      avatarUrl: null,
      createdAt: null,
    });

    mockProfileApi.updateMe.mockResolvedValue({
      id: "user-123",
      email: "alex.jones@example.com",
      name: "Alex Updated",
      avatarUrl: null,
      createdAt: null,
    });

    mockProfileApi.signOutAllDevices.mockResolvedValue(undefined);
    mockProfileApi.deletePersonalAccount.mockResolvedValue(undefined);
    mockProfileApi.changePassword.mockResolvedValue(undefined);
    mockProfileApi.removeAvatar.mockResolvedValue(undefined);
    mockProfileApi.uploadAvatar.mockResolvedValue({
      id: "user-123",
      email: "alex.jones@example.com",
      name: "Alex Jones",
      avatarUrl: "https://example.com/avatar.jpg",
      createdAt: null,
    });
  });

  // ── Account Identity ──────────────────────────────────────────────────────────

  it("renders account identity section with session data", async () => {
    renderTab();

    expect(
      await screen.findByRole("region", { name: "Account identity section" }),
    ).toBeInTheDocument();
    expect(
      screen.getByDisplayValue("alex.jones@example.com"),
    ).toBeInTheDocument();
    expect(screen.getByText("user-123")).toBeInTheDocument();
    expect(screen.getByText("Member")).toBeInTheDocument();
  });

  it("shows initials avatar derived from email when no me API", async () => {
    renderTab();

    const avatar = await screen.findByRole("button", {
      name: "User initials avatar",
    });
    expect(avatar).toBeInTheDocument();
    expect(avatar.textContent).toContain("AJ");
  });

  it("shows email input in account identity", async () => {
    renderTab();

    await screen.findByRole("region", { name: "Account identity section" });
    expect(
      screen.getByDisplayValue("alex.jones@example.com"),
    ).toBeInTheDocument();
  });

  it("shows multilingual help link next to display language", async () => {
    renderTab();

    await screen.findByRole("region", { name: "Account identity section" });
    expect(
      screen.getByRole("button", { name: "Open help for this topic" }),
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
    expect(
      await screen.findByRole("button", { name: "Copied!" }),
    ).toBeInTheDocument();
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

  it("shows editable name input when meEnabled capability is on", async () => {
    mockProfileApi.capabilities = {
      ...mockProfileApi.capabilities,
      meEnabled: true,
    };

    renderTab();

    const nameInput = await screen.findByDisplayValue("Alex Jones");
    expect(nameInput).toBeInTheDocument();
    expect(nameInput).not.toHaveAttribute("readonly");
  });

  it("shows read-only name when meEnabled is false", async () => {
    renderTab();

    await screen.findByRole("region", { name: "Account identity section" });
    const nameInput = screen.getByDisplayValue("Alex Jones");
    expect(nameInput).toHaveAttribute("readonly");
  });

  it("shows change password button when changePasswordEnabled", async () => {
    mockProfileApi.capabilities = {
      ...mockProfileApi.capabilities,
      changePasswordEnabled: true,
    };

    renderTab();

    expect(
      await screen.findByRole("button", { name: /change password/i }),
    ).toBeInTheDocument();
  });

  it("shows change password unavailable message when not enabled", async () => {
    renderTab();

    await screen.findByRole("region", { name: "Account identity section" });
    expect(
      screen.getByText(/password change is not available/i),
    ).toBeInTheDocument();
  });

  it("opens and closes change password dialog", async () => {
    mockProfileApi.capabilities = {
      ...mockProfileApi.capabilities,
      changePasswordEnabled: true,
    };

    renderTab();

    await userEvent.click(
      await screen.findByRole("button", { name: /change password/i }),
    );

    expect(
      screen.getByRole("dialog", { name: "Change Password" }),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(
      screen.queryByRole("dialog", { name: "Change Password" }),
    ).not.toBeInTheDocument();
  });

  it("submits change password form", async () => {
    mockProfileApi.capabilities = {
      ...mockProfileApi.capabilities,
      changePasswordEnabled: true,
    };

    renderTab();

    await userEvent.click(
      await screen.findByRole("button", { name: /change password/i }),
    );

    const dialog = screen.getByRole("dialog", { name: "Change Password" });

    await userEvent.type(
      within(dialog).getByLabelText("Current Password"),
      "OldPass123!",
    );
    await userEvent.type(
      within(dialog).getByLabelText("New Password"),
      "NewPass456!",
    );
    await userEvent.type(
      within(dialog).getByLabelText("Confirm New Password"),
      "NewPass456!",
    );

    await userEvent.click(
      within(dialog).getByRole("button", { name: /change password/i }),
    );

    await waitFor(() => {
      expect(mockProfileApi.changePassword).toHaveBeenCalledWith(
        "OldPass123!",
        "NewPass456!",
        "NewPass456!",
      );
    });
  });

  it("shows upload avatar button when avatarEnabled", async () => {
    mockProfileApi.capabilities = {
      ...mockProfileApi.capabilities,
      avatarEnabled: true,
    };

    renderTab();

    expect(
      await screen.findByRole("button", { name: /upload photo/i }),
    ).toBeInTheDocument();
  });

  it("shows avatar unavailable message when not enabled", async () => {
    renderTab();

    await screen.findByRole("region", { name: "Account identity section" });
    expect(
      screen.getByText(/avatar upload is not configured/i),
    ).toBeInTheDocument();
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

  it("applies Persian language and RTL direction when preferences are saved", async () => {
    renderTab();

    const langSelect = await screen.findByLabelText("Display Language");
    await userEvent.selectOptions(langSelect, "fa");
    await userEvent.click(
      screen.getByRole("button", { name: "Update Profile" }),
    );

    await waitFor(() => {
      expect(document.cookie).toContain("NEXT_LOCALE=fa");
      expect(document.documentElement).toHaveAttribute("lang", "fa");
      expect(document.documentElement).toHaveAttribute("dir", "rtl");
      expect(mockState.refresh).toHaveBeenCalled();
    });
  });

  it("applies Arabic language and RTL direction when preferences are saved", async () => {
    renderTab();

    const langSelect = await screen.findByLabelText("Display Language");
    await userEvent.selectOptions(langSelect, "ar");
    await userEvent.click(
      screen.getByRole("button", { name: "Update Profile" }),
    );

    await waitFor(() => {
      expect(document.cookie).toContain("NEXT_LOCALE=ar");
      expect(document.documentElement).toHaveAttribute("lang", "ar");
      expect(document.documentElement).toHaveAttribute("dir", "rtl");
      expect(mockState.refresh).toHaveBeenCalled();
    });
  });

  it("discards personal preference changes", async () => {
    renderTab();

    const langSelect = await screen.findByLabelText("Display Language");
    await userEvent.selectOptions(langSelect, "fr");

    const discardBtn = screen.getByRole("button", { name: "Discard Changes" });
    expect(discardBtn).not.toBeDisabled();

    await userEvent.click(discardBtn);

    expect(mockSchemas.saveProfileUiPreferences).not.toHaveBeenCalled();
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

  it("renders confidence threshold slider", async () => {
    renderTab();

    expect(
      await screen.findByLabelText("Confidence Threshold"),
    ).toBeInTheDocument();
  });

  it("shows expert mode toggle button", async () => {
    renderTab();

    expect(
      await screen.findByRole("switch", { name: /expert mode/i }),
    ).toBeInTheDocument();
  });

  it("toggles expert mode on click", async () => {
    renderTab();

    const expertBtn = await screen.findByRole("switch", {
      name: /expert mode/i,
    });
    expect(expertBtn).toHaveAttribute("aria-checked", "false");

    await userEvent.click(expertBtn);
    expect(expertBtn).toHaveAttribute("aria-checked", "true");
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

    await screen.findByRole("region", {
      name: "AI and retrieval defaults section",
    });

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
      meEnabled: false,
      preferencesEnabled: false,
      signOutAllDevicesEnabled: true,
      deleteAccountEnabled: false,
      avatarEnabled: false,
      changePasswordEnabled: false,
    };

    renderTab();

    await screen.findByRole("region", { name: "Account actions section" });
    expect(
      screen.getByRole("button", { name: "Sign out everywhere" }),
    ).toBeInTheDocument();
  });

  it("shows confirmation dialog before sign-out-all", async () => {
    mockProfileApi.capabilities = {
      ...mockProfileApi.capabilities,
      signOutAllDevicesEnabled: true,
    };

    renderTab();

    await userEvent.click(
      await screen.findByRole("button", { name: "Sign out everywhere" }),
    );

    expect(
      screen.getByRole("dialog", { name: "Sign out everywhere?" }),
    ).toBeInTheDocument();
  });

  it("calls signOutAllDevices when dialog is confirmed", async () => {
    mockProfileApi.capabilities = {
      ...mockProfileApi.capabilities,
      signOutAllDevicesEnabled: true,
    };

    renderTab();

    await userEvent.click(
      await screen.findByRole("button", { name: "Sign out everywhere" }),
    );

    const dialog = screen.getByRole("dialog", { name: "Sign out everywhere?" });
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Sign out everywhere" }),
    );

    await waitFor(() => {
      expect(mockProfileApi.signOutAllDevices).toHaveBeenCalledTimes(1);
    });
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
      meEnabled: false,
      preferencesEnabled: false,
      signOutAllDevicesEnabled: false,
      deleteAccountEnabled: true,
      avatarEnabled: false,
      changePasswordEnabled: false,
    };

    renderTab();

    await screen.findByRole("region", { name: "Account actions section" });
    expect(
      screen.getByRole("button", { name: "Delete account" }),
    ).toBeInTheDocument();
  });

  it("shows delete account confirmation dialog with email input", async () => {
    mockProfileApi.capabilities = {
      ...mockProfileApi.capabilities,
      deleteAccountEnabled: true,
    };

    renderTab();

    await userEvent.click(
      await screen.findByRole("button", { name: "Delete account" }),
    );

    const dialog = screen.getByRole("dialog", {
      name: "Delete your account?",
    });
    expect(dialog).toBeInTheDocument();
    expect(
      within(dialog).getByLabelText(/type your email/i),
    ).toBeInTheDocument();
  });

  it("requires correct email before deleting account", async () => {
    mockProfileApi.capabilities = {
      ...mockProfileApi.capabilities,
      deleteAccountEnabled: true,
    };

    renderTab();

    await userEvent.click(
      await screen.findByRole("button", { name: "Delete account" }),
    );

    const dialog = screen.getByRole("dialog", { name: "Delete your account?" });

    // Type wrong email — should not call delete
    await userEvent.type(
      within(dialog).getByLabelText(/type your email/i),
      "wrong@example.com",
    );

    await userEvent.click(
      within(dialog).getByRole("button", {
        name: /permanently delete my account/i,
      }),
    );

    expect(mockProfileApi.deletePersonalAccount).not.toHaveBeenCalled();
  });

  it("calls deletePersonalAccount when correct email is typed", async () => {
    mockProfileApi.capabilities = {
      ...mockProfileApi.capabilities,
      deleteAccountEnabled: true,
    };

    renderTab();

    await userEvent.click(
      await screen.findByRole("button", { name: "Delete account" }),
    );

    const dialog = screen.getByRole("dialog", { name: "Delete your account?" });

    await userEvent.type(
      within(dialog).getByLabelText(/type your email/i),
      "alex.jones@example.com",
    );

    await userEvent.click(
      within(dialog).getByRole("button", {
        name: /permanently delete my account/i,
      }),
    );

    await waitFor(() => {
      expect(mockProfileApi.deletePersonalAccount).toHaveBeenCalledTimes(1);
    });
  });
});
