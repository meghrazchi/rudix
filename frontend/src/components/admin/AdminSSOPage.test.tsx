import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminSSOPage } from "@/components/admin/AdminSSOPage";
import type { SessionState } from "@/lib/auth-session";
import type { SSOConfig, TestConnectionResponse } from "@/lib/api/sso";

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  getSSOConfig: vi.fn(),
  upsertSSOConfig: vi.fn(),
  deleteSSOConfig: vi.fn(),
  testSSOConnection: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/sso", () => ({
  getSSOConfig: () => mockApi.getSSOConfig(),
  upsertSSOConfig: (payload: unknown) => mockApi.upsertSSOConfig(payload),
  deleteSSOConfig: () => mockApi.deleteSSOConfig(),
  testSSOConnection: (payload: unknown) => mockApi.testSSOConnection(payload),
}));

vi.mock("@/lib/dashboard", () => ({
  canViewAdminUsage: (role: string | undefined) =>
    role === "owner" || role === "admin",
}));

vi.mock("@/lib/forbidden", () => ({
  isForbiddenError: () => false,
  extractRequestIdFromError: () => null,
  getSupportAction: () => null,
  sanitizeRequestId: () => null,
}));

const OWNER_SESSION = {
  status: "authenticated" as const,
  session: {
    userId: "user-1",
    email: "owner@acme.com",
    role: "owner" as const,
    organizationId: "org-1",
    organizationName: "ACME Corp",
    accessToken: "tok",
    refreshToken: null,
  },
};

const ADMIN_SESSION = {
  ...OWNER_SESSION,
  session: { ...OWNER_SESSION.session, role: "admin" as const },
};

const MEMBER_SESSION = {
  ...OWNER_SESSION,
  session: { ...OWNER_SESSION.session, role: "member" as const },
};

const SAMPLE_CONFIG: SSOConfig = {
  id: "cfg-1",
  organization_id: "org-1",
  sso_type: "saml",
  domain: "acme.com",
  enabled: true,
  idp_metadata_url: "https://idp.acme.com/metadata",
  sp_entity_id: "https://app.rudix.com/auth/sso/org-1/metadata",
  sp_acs_url: "https://api.rudix.com/api/v1/auth/sso/org-1/callback",
  idp_entity_id: "https://idp.acme.com",
  idp_sso_url: "https://idp.acme.com/sso",
  attribute_mapping: {},
  last_test_at: null,
  last_test_result: null,
  created_at: "2026-06-05T00:00:00Z",
  updated_at: "2026-06-05T00:00:00Z",
};

const TEST_SUCCESS: TestConnectionResponse = {
  success: true,
  result: "success",
  detail: "IdP metadata URL is reachable.",
  checked_at: "2026-06-05T00:00:00Z",
};

const TEST_FAILURE: TestConnectionResponse = {
  success: false,
  result: "failure",
  detail: "Could not reach IdP.",
  checked_at: "2026-06-05T00:00:00Z",
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
      <AdminSSOPage />
    </QueryClientProvider>,
  );
}

describe("AdminSSOPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockState.authState = OWNER_SESSION;
  });

  it("shows forbidden state for non-admin", async () => {
    mockState.authState = MEMBER_SESSION;
    renderPage();
    expect(
      screen.getAllByText(/forbidden|permission|access/i).length,
    ).toBeGreaterThan(0);
  });

  it("shows loading state while fetching", () => {
    mockApi.getSSOConfig.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByText(/loading/i)).toBeTruthy();
  });

  it("shows form when no config exists", async () => {
    mockApi.getSSOConfig.mockResolvedValue(null);
    renderPage();
    await waitFor(() => expect(screen.getByText(/email domain/i)).toBeTruthy());
    expect(screen.getByPlaceholderText("company.com")).toBeTruthy();
  });

  it("shows read view when config exists", async () => {
    mockApi.getSSOConfig.mockResolvedValue(SAMPLE_CONFIG);
    renderPage();
    await waitFor(() => expect(screen.getByText("acme.com")).toBeTruthy());
    expect(screen.getByText("Enabled")).toBeTruthy();
    expect(screen.getByText("Edit")).toBeTruthy();
  });

  it("shows SP entity ID and ACS URL for copy", async () => {
    mockApi.getSSOConfig.mockResolvedValue(SAMPLE_CONFIG);
    renderPage();
    await waitFor(() => expect(screen.getByText(/sp entity id/i)).toBeTruthy());
    expect(screen.getByText(SAMPLE_CONFIG.sp_entity_id)).toBeTruthy();
    expect(screen.getByText(SAMPLE_CONFIG.sp_acs_url)).toBeTruthy();
  });

  it("enters edit mode and shows form", async () => {
    mockApi.getSSOConfig.mockResolvedValue(SAMPLE_CONFIG);
    renderPage();
    await waitFor(() => screen.getByText("Edit"));
    fireEvent.click(screen.getByText("Edit"));
    expect(screen.getByPlaceholderText("company.com")).toBeTruthy();
  });

  it("admin can view config but not see Edit button", async () => {
    mockState.authState = ADMIN_SESSION;
    mockApi.getSSOConfig.mockResolvedValue(SAMPLE_CONFIG);
    renderPage();
    await waitFor(() => screen.getByText("acme.com"));
    expect(screen.queryByText("Edit")).toBeNull();
  });

  it("saves config successfully", async () => {
    mockApi.getSSOConfig.mockResolvedValue(null);
    mockApi.upsertSSOConfig.mockResolvedValue({
      ...SAMPLE_CONFIG,
      domain: "new-corp.com",
    });
    renderPage();
    await waitFor(() => screen.getByPlaceholderText("company.com"));

    fireEvent.change(screen.getByPlaceholderText("company.com"), {
      target: { value: "new-corp.com" },
    });
    fireEvent.click(screen.getByText("Save Configuration"));
    await waitFor(() => expect(mockApi.upsertSSOConfig).toHaveBeenCalledOnce());
    expect(mockApi.upsertSSOConfig).toHaveBeenCalledWith(
      expect.objectContaining({ domain: "new-corp.com" }),
    );
  });

  it("save button is disabled when domain is empty", async () => {
    mockApi.getSSOConfig.mockResolvedValue(null);
    renderPage();
    await waitFor(() => screen.getByPlaceholderText("company.com"));
    const saveBtn = screen.getByText("Save Configuration");
    expect(saveBtn).toHaveProperty("disabled", true);
  });

  it("test connection shows success banner", async () => {
    mockApi.getSSOConfig.mockResolvedValue(null);
    mockApi.testSSOConnection.mockResolvedValue(TEST_SUCCESS);
    renderPage();
    await waitFor(() => screen.getByText("Test Connection"));
    fireEvent.click(screen.getByText("Test Connection"));
    await waitFor(() =>
      expect(screen.getByText(/connection succeeded/i)).toBeTruthy(),
    );
  });

  it("test connection shows failure banner", async () => {
    mockApi.getSSOConfig.mockResolvedValue(null);
    mockApi.testSSOConnection.mockResolvedValue(TEST_FAILURE);
    renderPage();
    await waitFor(() => screen.getByText("Test Connection"));
    fireEvent.click(screen.getByText("Test Connection"));
    await waitFor(() =>
      expect(screen.getByText(/connection failed/i)).toBeTruthy(),
    );
    expect(screen.getByText("Could not reach IdP.")).toBeTruthy();
  });

  it("shows delete confirm modal and calls delete", async () => {
    mockApi.getSSOConfig.mockResolvedValue(SAMPLE_CONFIG);
    mockApi.deleteSSOConfig.mockResolvedValue(undefined);
    renderPage();
    await waitFor(() => screen.getByText("Remove"));
    fireEvent.click(screen.getByText("Remove"));
    expect(screen.getByText(/remove sso\?/i)).toBeTruthy();
    fireEvent.click(screen.getByText("Remove SSO"));
    await waitFor(() => expect(mockApi.deleteSSOConfig).toHaveBeenCalledOnce());
  });

  it("cancel in delete modal does not call delete", async () => {
    mockApi.getSSOConfig.mockResolvedValue(SAMPLE_CONFIG);
    renderPage();
    await waitFor(() => screen.getByText("Remove"));
    fireEvent.click(screen.getByText("Remove"));
    fireEvent.click(screen.getByText("Cancel"));
    expect(mockApi.deleteSSOConfig).not.toHaveBeenCalled();
  });

  it("shows XML paste mode when radio toggled", async () => {
    mockApi.getSSOConfig.mockResolvedValue(null);
    renderPage();
    // wait for form to appear (no existing config → form shown immediately)
    await waitFor(() =>
      expect(
        screen.getByPlaceholderText("https://idp.company.com/metadata"),
      ).toBeTruthy(),
    );
    // Both radio options should be present
    expect(screen.getByRole("radio", { name: /metadata url/i })).toBeTruthy();
    expect(screen.getByRole("radio", { name: /paste xml/i })).toBeTruthy();
    // URL mode radio should be checked by default
    expect(screen.getByRole("radio", { name: /metadata url/i })).toBeChecked();
    // XML radio exists and is not checked
    expect(screen.getByRole("radio", { name: /paste xml/i })).not.toBeChecked();
  });
});
