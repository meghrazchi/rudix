import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminSCIMPage } from "@/components/admin/AdminSCIMPage";
import type { SessionState } from "@/lib/auth-session";
import type {
  DomainVerification,
  SCIMConfig,
  SCIMEnableResponse,
} from "@/lib/api/scim";

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  getSCIMConfig: vi.fn(),
  enableSCIM: vi.fn(),
  rotateSCIMToken: vi.fn(),
  disableSCIM: vi.fn(),
  listDomainVerifications: vi.fn(),
  initiateDomainVerification: vi.fn(),
  checkDomainVerification: vi.fn(),
  deleteDomainVerification: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/scim", () => ({
  getSCIMConfig: () => mockApi.getSCIMConfig(),
  enableSCIM: () => mockApi.enableSCIM(),
  rotateSCIMToken: () => mockApi.rotateSCIMToken(),
  disableSCIM: () => mockApi.disableSCIM(),
  listDomainVerifications: () => mockApi.listDomainVerifications(),
  initiateDomainVerification: (p: unknown) =>
    mockApi.initiateDomainVerification(p),
  checkDomainVerification: (id: string) => mockApi.checkDomainVerification(id),
  deleteDomainVerification: (id: string) =>
    mockApi.deleteDomainVerification(id),
}));

vi.mock("@/lib/dashboard", () => ({
  canViewAdminUsage: (role: string | undefined) =>
    role === "owner" || role === "admin",
}));

vi.mock("@/lib/forbidden", () => ({
  isForbiddenError: () => false,
  extractRequestIdFromError: () => null,
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

const MOCK_SCIM_CONFIG: SCIMConfig = {
  id: "scim-cfg-1",
  organization_id: "org-1",
  enabled: true,
  token_hint: "abcd",
  scim_base_url: "http://localhost:8000/api/v1/scim/v2",
  last_sync_at: null,
  last_sync_error: null,
  provisioned_count: 5,
  deprovisioned_count: 1,
  created_at: "2026-06-05T00:00:00Z",
  updated_at: "2026-06-05T00:00:00Z",
};

const MOCK_DOMAIN: DomainVerification = {
  id: "dv-1",
  organization_id: "org-1",
  domain: "acme.com",
  status: "pending",
  verification_token: "abc123token456",
  txt_record_name: "_rudix-challenge.acme.com",
  txt_record_value: "rudix-domain-verify=abc123token456",
  verified_at: null,
  last_checked_at: null,
  failure_reason: null,
  created_at: "2026-06-05T00:00:00Z",
  updated_at: "2026-06-05T00:00:00Z",
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AdminSCIMPage />
    </QueryClientProvider>,
  );
}

describe("AdminSCIMPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockState.authState = OWNER_SESSION;
    mockApi.getSCIMConfig.mockResolvedValue(null);
    mockApi.listDomainVerifications.mockResolvedValue([]);
  });

  it("shows ForbiddenState for non-admin roles", async () => {
    mockState.authState = MEMBER_SESSION;
    renderPage();
    await waitFor(() => {
      expect(screen.queryByText("SCIM 2.0 Provisioning")).toBeNull();
    });
  });

  it("renders the page heading for an owner", async () => {
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByText("SCIM Provisioning & Domain Verification"),
      ).toBeDefined();
    });
  });

  it("shows 'Not configured' when SCIM is not set up", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Not configured")).toBeDefined();
    });
  });

  it("shows 'Enable SCIM' button for owner when not configured", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Enable SCIM")).toBeDefined();
    });
  });

  it("does not show 'Enable SCIM' button for admin (non-owner)", async () => {
    mockState.authState = ADMIN_SESSION;
    renderPage();
    await waitFor(() => {
      expect(screen.queryByText("Enable SCIM")).toBeNull();
      expect(
        screen.getByText("Only owners can configure SCIM provisioning."),
      ).toBeDefined();
    });
  });

  it("shows bearer token after enabling SCIM", async () => {
    const enableResponse: SCIMEnableResponse = {
      config: MOCK_SCIM_CONFIG,
      bearer_token: "a".repeat(64),
    };
    mockApi.enableSCIM.mockResolvedValue(enableResponse);

    renderPage();
    await waitFor(() => expect(screen.getByText("Enable SCIM")).toBeDefined());
    fireEvent.click(screen.getByText("Enable SCIM"));

    await waitFor(() => {
      expect(
        screen.getByText(
          "Save your SCIM bearer token — it will not be shown again.",
        ),
      ).toBeDefined();
      expect(screen.getByText("a".repeat(64))).toBeDefined();
    });
  });

  it("shows existing SCIM config with token hint and stats", async () => {
    mockApi.getSCIMConfig.mockResolvedValue(MOCK_SCIM_CONFIG);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Active")).toBeDefined();
      expect(screen.getByText("…abcd")).toBeDefined();
      expect(screen.getByText("5")).toBeDefined(); // provisioned_count
      expect(screen.getByText("1")).toBeDefined(); // deprovisioned_count
    });
  });

  it("shows Rotate Token and Disable SCIM buttons when configured", async () => {
    mockApi.getSCIMConfig.mockResolvedValue(MOCK_SCIM_CONFIG);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Rotate Token")).toBeDefined();
      expect(screen.getByText("Disable SCIM")).toBeDefined();
    });
  });

  it("shows disable confirmation modal when clicking Disable SCIM", async () => {
    mockApi.getSCIMConfig.mockResolvedValue(MOCK_SCIM_CONFIG);
    renderPage();
    await waitFor(() => expect(screen.getByText("Disable SCIM")).toBeDefined());
    fireEvent.click(screen.getByText("Disable SCIM"));
    await waitFor(() => {
      expect(screen.getByText("Disable SCIM?")).toBeDefined();
    });
  });

  it("dismisses the new token banner when user clicks 'I've saved it'", async () => {
    const enableResponse: SCIMEnableResponse = {
      config: MOCK_SCIM_CONFIG,
      bearer_token: "b".repeat(64),
    };
    mockApi.enableSCIM.mockResolvedValue(enableResponse);

    renderPage();
    await waitFor(() => expect(screen.getByText("Enable SCIM")).toBeDefined());
    fireEvent.click(screen.getByText("Enable SCIM"));

    await waitFor(() =>
      expect(screen.getByText(/I've saved it/)).toBeDefined(),
    );
    fireEvent.click(screen.getByText(/I've saved it/));

    await waitFor(() => {
      expect(
        screen.queryByText(
          "Save your SCIM bearer token — it will not be shown again.",
        ),
      ).toBeNull();
    });
  });

  // ── Domain verification ───────────────────────────────────────────────────

  it("renders empty domain state", async () => {
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByText(
          "No domains added yet. Add a domain above to start verification.",
        ),
      ).toBeDefined();
    });
  });

  it("shows a pending domain verification card", async () => {
    mockApi.listDomainVerifications.mockResolvedValue([MOCK_DOMAIN]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("acme.com")).toBeDefined();
      expect(screen.getByText("pending")).toBeDefined();
    });
  });

  it("adds a domain when owner submits the form", async () => {
    mockApi.initiateDomainVerification.mockResolvedValue({
      ...MOCK_DOMAIN,
      domain: "new.com",
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByPlaceholderText("company.com")).toBeDefined(),
    );
    fireEvent.change(screen.getByPlaceholderText("company.com"), {
      target: { value: "new.com" },
    });
    fireEvent.click(screen.getByText("Add Domain"));

    await waitFor(() => {
      expect(mockApi.initiateDomainVerification).toHaveBeenCalledWith({
        domain: "new.com",
      });
    });
  });

  it("shows DNS instructions when clicking Instructions button", async () => {
    mockApi.listDomainVerifications.mockResolvedValue([MOCK_DOMAIN]);
    renderPage();
    await waitFor(() => expect(screen.getByText("Instructions")).toBeDefined());
    fireEvent.click(screen.getByText("Instructions"));

    await waitFor(() => {
      expect(screen.getByText("_rudix-challenge.acme.com")).toBeDefined();
      expect(
        screen.getByText("rudix-domain-verify=abc123token456"),
      ).toBeDefined();
    });
  });

  it("shows verified badge for verified domain", async () => {
    const verifiedDomain: DomainVerification = {
      ...MOCK_DOMAIN,
      status: "verified",
      verified_at: "2026-06-05T10:00:00Z",
    };
    mockApi.listDomainVerifications.mockResolvedValue([verifiedDomain]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("verified")).toBeDefined();
      expect(screen.queryByText("Check DNS")).toBeNull();
    });
  });
});
