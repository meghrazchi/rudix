import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SecuritySettingsTab } from "@/components/settings/SecuritySettingsTab";
import type { SessionState } from "@/lib/auth-session";
import type {
  SecurityCapabilities,
  SecuritySession,
  LoginPolicy,
  SecurityPosture,
  AuditEvent,
} from "@/lib/api/security";

// ── Mock: auth session ────────────────────────────────────────────────────────

const mockAuth = vi.hoisted(() => ({
  state: { status: "authenticated", session: null } as SessionState,
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({ state: mockAuth.state }),
}));

// ── Mock: runtime config ──────────────────────────────────────────────────────

vi.mock("@/lib/runtime-config", () => ({
  getFrontendRuntimeConfig: () => ({
    apiUrl: "http://localhost:8000/api/v1",
    appUrl: "http://localhost:3000",
    authProvider: "app",
    authProviderRaw: "app",
    features: {
      developerMode: false,
      feedback: false,
      exports: false,
      unavailableBackendEndpoints: false,
    },
  }),
}));

// ── Mock: request (for getJwtExpirationTimeMs) ────────────────────────────────

vi.mock("@/lib/api/request", () => ({
  getJwtExpirationTimeMs: () => null,
  apiRequest: vi.fn(),
}));

// ── Mock: security API ────────────────────────────────────────────────────────

const mockSecurityApi = vi.hoisted(() => ({
  capabilities: {
    sessionsEnabled: false,
    revokeSessionEnabled: false,
    revokeAllSessionsEnabled: false,
    loginPolicyEnabled: false,
    postureEnabled: false,
    auditEnabled: false,
    auditExportEnabled: false,
  } as SecurityCapabilities,
  getSessions: vi.fn(),
  revokeSession: vi.fn(),
  revokeAllOtherSessions: vi.fn(),
  getLoginPolicy: vi.fn(),
  updateLoginPolicy: vi.fn(),
  getSecurityPosture: vi.fn(),
  getRecentAuditEvents: vi.fn(),
}));

vi.mock("@/lib/api/security", () => ({
  getSecurityCapabilities: () => mockSecurityApi.capabilities,
  getSessions: (...args: unknown[]) => mockSecurityApi.getSessions(...args),
  revokeSession: (...args: unknown[]) => mockSecurityApi.revokeSession(...args),
  revokeAllOtherSessions: (...args: unknown[]) =>
    mockSecurityApi.revokeAllOtherSessions(...args),
  getLoginPolicy: (...args: unknown[]) =>
    mockSecurityApi.getLoginPolicy(...args),
  updateLoginPolicy: (...args: unknown[]) =>
    mockSecurityApi.updateLoginPolicy(...args),
  getSecurityPosture: (...args: unknown[]) =>
    mockSecurityApi.getSecurityPosture(...args),
  getRecentAuditEvents: (...args: unknown[]) =>
    mockSecurityApi.getRecentAuditEvents(...args),
}));

// ── Fixtures ──────────────────────────────────────────────────────────────────

const FAKE_ACCESS_TOKEN = "eyJfakeAccessToken123.secret.value";
const FAKE_REFRESH_TOKEN = "rt_fakeRefreshTokenSecret456";

const OWNER_SESSION: SessionState = {
  status: "authenticated",
  session: {
    userId: "user-1",
    email: "owner@example.com",
    role: "owner",
    organizationId: "org-abc",
    organizationName: "Acme Corp",
    accessToken: FAKE_ACCESS_TOKEN,
    refreshToken: FAKE_REFRESH_TOKEN,
  },
};

const ADMIN_SESSION: SessionState = {
  status: "authenticated",
  session: {
    userId: "user-2",
    email: "admin@example.com",
    role: "admin",
    organizationId: "org-abc",
    organizationName: "Acme Corp",
    accessToken: FAKE_ACCESS_TOKEN,
    refreshToken: FAKE_REFRESH_TOKEN,
  },
};

const MEMBER_SESSION: SessionState = {
  status: "authenticated",
  session: {
    userId: "user-3",
    email: "member@example.com",
    role: "member",
    organizationId: "org-abc",
    organizationName: "Acme Corp",
    accessToken: FAKE_ACCESS_TOKEN,
    refreshToken: null,
  },
};

const VIEWER_SESSION: SessionState = {
  status: "authenticated",
  session: {
    userId: "user-4",
    email: "viewer@example.com",
    role: "viewer",
    organizationId: "org-abc",
    organizationName: "Acme Corp",
  },
};

const SESSIONS_FIXTURE: SecuritySession[] = [
  {
    id: "sess-1",
    device: "MacBook Pro (Chrome)",
    ip_address: "192.168.1.1",
    location: "San Francisco, US",
    created_at: "2025-05-01T10:00:00Z",
    last_active_at: "2025-05-30T08:00:00Z",
    is_current: true,
  },
  {
    id: "sess-2",
    device: "iPhone 15 (App)",
    ip_address: "72.14.192.3",
    location: "Los Angeles, US",
    created_at: "2025-05-20T12:00:00Z",
    last_active_at: "2025-05-29T20:00:00Z",
    is_current: false,
  },
];

const LOGIN_POLICY_FIXTURE: LoginPolicy = {
  domain_allowlist: ["acme.com", "partner.org"],
  session_timeout_hours: 24,
  sso_required: false,
  invite_only: true,
  mfa_required: false,
};

const POSTURE_FIXTURE: SecurityPosture = {
  prompt_injection_protection: true,
  citation_validation: true,
  tenant_isolation: true,
  output_validation: false,
  tool_policy_enforced: null,
  last_audit_at: "2025-05-30T07:00:00Z",
};

const AUDIT_FIXTURE: AuditEvent[] = [
  {
    id: "evt-1",
    event_type: "session_revoked",
    actor_email: "owner@example.com",
    created_at: "2025-05-30T07:00:00Z",
    summary: "Session revoked for user@example.com",
  },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function renderTab() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <SecuritySettingsTab />
    </QueryClientProvider>,
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("SecuritySettingsTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuth.state = { ...OWNER_SESSION };
    mockSecurityApi.capabilities = {
      sessionsEnabled: false,
      revokeSessionEnabled: false,
      revokeAllSessionsEnabled: false,
      loginPolicyEnabled: false,
      postureEnabled: false,
      auditEnabled: false,
      auditExportEnabled: false,
    };
  });

  describe("token safety", () => {
    it("never renders the access token value in the DOM", () => {
      mockAuth.state = { ...OWNER_SESSION };
      renderTab();
      expect(
        document.body.textContent?.includes(FAKE_ACCESS_TOKEN),
      ).toBe(false);
    });

    it("never renders the refresh token value in the DOM", () => {
      mockAuth.state = { ...OWNER_SESSION };
      renderTab();
      expect(
        document.body.textContent?.includes(FAKE_REFRESH_TOKEN),
      ).toBe(false);
    });

    it("shows Yes/No booleans for token presence instead of token values", () => {
      mockAuth.state = { ...OWNER_SESSION };
      renderTab();
      expect(screen.getByText("Access token attached")).toBeInTheDocument();
      expect(screen.getByText("Refresh token available")).toBeInTheDocument();
      const yesElements = screen.getAllByText("Yes");
      expect(yesElements.length).toBeGreaterThanOrEqual(2);
    });

    it("shows No when access token is absent", () => {
      mockAuth.state = { ...VIEWER_SESSION };
      renderTab();
      const noElements = screen.getAllByText("No");
      expect(noElements.length).toBeGreaterThanOrEqual(1);
    });

    it("never renders tokens even when member session has token strings", () => {
      mockAuth.state = { ...MEMBER_SESSION };
      renderTab();
      expect(
        document.body.textContent?.includes(FAKE_ACCESS_TOKEN),
      ).toBe(false);
    });
  });

  describe("auth diagnostics", () => {
    it("renders auth provider label", () => {
      renderTab();
      expect(screen.getByText("Auth provider")).toBeInTheDocument();
      expect(screen.getByText("App")).toBeInTheDocument();
    });

    it("renders user email from session", () => {
      mockAuth.state = { ...OWNER_SESSION };
      renderTab();
      expect(screen.getByText("owner@example.com")).toBeInTheDocument();
    });

    it("renders role from session", () => {
      mockAuth.state = { ...MEMBER_SESSION };
      renderTab();
      expect(screen.getByText("Role")).toBeInTheDocument();
      const roleValues = screen.getAllByText("member");
      expect(roleValues.length).toBeGreaterThanOrEqual(1);
    });

    it("renders organization ID from session", () => {
      mockAuth.state = { ...OWNER_SESSION };
      renderTab();
      expect(screen.getByText("org-abc")).toBeInTheDocument();
    });

    it("shows token safety notice", () => {
      renderTab();
      expect(
        screen.getByText(/Token values are never displayed/i),
      ).toBeInTheDocument();
    });
  });

  describe("active sessions — unavailable", () => {
    it("shows deployment-controlled message when sessions endpoint not configured", () => {
      mockSecurityApi.capabilities = {
        ...mockSecurityApi.capabilities,
        sessionsEnabled: false,
      };
      renderTab();
      expect(
        screen.getByText(/Session management is not available/i),
      ).toBeInTheDocument();
    });
  });

  describe("active sessions — available", () => {
    beforeEach(() => {
      mockSecurityApi.capabilities = {
        ...mockSecurityApi.capabilities,
        sessionsEnabled: true,
        revokeSessionEnabled: true,
        revokeAllSessionsEnabled: true,
      };
      mockSecurityApi.getSessions.mockResolvedValue(SESSIONS_FIXTURE);
    });

    it("renders session devices when loaded", async () => {
      renderTab();
      await waitFor(() => {
        expect(
          screen.getByText("MacBook Pro (Chrome)"),
        ).toBeInTheDocument();
      });
      expect(screen.getByText("iPhone 15 (App)")).toBeInTheDocument();
    });

    it("marks current session with Current badge", async () => {
      renderTab();
      await waitFor(() => {
        expect(screen.getByText("Current")).toBeInTheDocument();
      });
    });

    it("shows Revoke button for non-current sessions", async () => {
      renderTab();
      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /Revoke$/i }),
        ).toBeInTheDocument();
      });
    });

    it("shows confirmation dialog before revoking a session", async () => {
      const confirmSpy = vi
        .spyOn(window, "confirm")
        .mockReturnValue(false);
      mockSecurityApi.revokeSession.mockResolvedValue(undefined);

      renderTab();
      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /Revoke$/i }),
        ).toBeInTheDocument();
      });

      await userEvent.click(screen.getByRole("button", { name: /Revoke$/i }));
      expect(confirmSpy).toHaveBeenCalledOnce();
      expect(mockSecurityApi.revokeSession).not.toHaveBeenCalled();
    });

    it("calls revokeSession when confirmation accepted", async () => {
      vi.spyOn(window, "confirm").mockReturnValue(true);
      mockSecurityApi.revokeSession.mockResolvedValue(undefined);
      mockSecurityApi.getSessions.mockResolvedValue(SESSIONS_FIXTURE);

      renderTab();
      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /^Revoke$/ }),
        ).toBeInTheDocument();
      });

      await userEvent.click(screen.getByRole("button", { name: /^Revoke$/ }));
      await waitFor(() => {
        expect(mockSecurityApi.revokeSession).toHaveBeenCalledWith("sess-2");
      });
    });

    it("shows revoke all button when multiple sessions exist", async () => {
      renderTab();
      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /Revoke all other sessions/i }),
        ).toBeInTheDocument();
      });
    });

    it("shows confirmation before revoking all sessions", async () => {
      const confirmSpy = vi
        .spyOn(window, "confirm")
        .mockReturnValue(false);
      mockSecurityApi.revokeAllOtherSessions.mockResolvedValue(undefined);

      renderTab();
      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /Revoke all other sessions/i }),
        ).toBeInTheDocument();
      });

      await userEvent.click(
        screen.getByRole("button", { name: /Revoke all other sessions/i }),
      );
      expect(confirmSpy).toHaveBeenCalledOnce();
      expect(mockSecurityApi.revokeAllOtherSessions).not.toHaveBeenCalled();
    });
  });

  describe("login policy — unavailable", () => {
    it("shows deployment-controlled when endpoint not configured", () => {
      mockSecurityApi.capabilities.loginPolicyEnabled = false;
      renderTab();
      expect(
        screen.getByText(/Login policy settings are not available/i),
      ).toBeInTheDocument();
    });
  });

  describe("login policy — owner/admin access", () => {
    beforeEach(() => {
      mockSecurityApi.capabilities = {
        ...mockSecurityApi.capabilities,
        loginPolicyEnabled: true,
      };
      mockSecurityApi.getLoginPolicy.mockResolvedValue(LOGIN_POLICY_FIXTURE);
    });

    it("owner sees login policy form", async () => {
      mockAuth.state = { ...OWNER_SESSION };
      renderTab();
      await waitFor(() => {
        expect(
          screen.getByLabelText(/Domain Allowlist/i),
        ).toBeInTheDocument();
      });
    });

    it("admin sees login policy form", async () => {
      mockAuth.state = { ...ADMIN_SESSION };
      renderTab();
      await waitFor(() => {
        expect(
          screen.getByLabelText(/Session Timeout/i),
        ).toBeInTheDocument();
      });
    });
  });

  describe("login policy — member/viewer access", () => {
    beforeEach(() => {
      mockSecurityApi.capabilities = {
        ...mockSecurityApi.capabilities,
        loginPolicyEnabled: true,
      };
    });

    it("member sees forbidden state for login policy", () => {
      mockAuth.state = { ...MEMBER_SESSION };
      renderTab();
      expect(
        screen.getByText(/Login policy can only be viewed and edited/i),
      ).toBeInTheDocument();
    });

    it("viewer sees forbidden state for login policy", () => {
      mockAuth.state = { ...VIEWER_SESSION };
      renderTab();
      expect(
        screen.getByText(/Login policy can only be viewed and edited/i),
      ).toBeInTheDocument();
    });
  });

  describe("role & access policy", () => {
    it("displays owner role capabilities", () => {
      mockAuth.state = { ...OWNER_SESSION };
      renderTab();
      const ownerEls = screen.getAllByText("owner");
      expect(ownerEls.length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText("Admin controls")).toBeInTheDocument();
      const fullAccessEl = screen.getAllByText("Full access");
      expect(fullAccessEl.length).toBeGreaterThan(0);
    });

    it("displays member role capabilities", () => {
      mockAuth.state = { ...MEMBER_SESSION };
      renderTab();
      const memberEls = screen.getAllByText("member");
      expect(memberEls.length).toBeGreaterThanOrEqual(1);
    });

    it("displays viewer role capabilities", () => {
      mockAuth.state = { ...VIEWER_SESSION };
      renderTab();
      const viewerEls = screen.getAllByText("viewer");
      expect(viewerEls.length).toBeGreaterThanOrEqual(1);
    });
  });

  describe("AI safety posture — unavailable", () => {
    it("shows unavailable notice when posture endpoint not configured", () => {
      mockSecurityApi.capabilities.postureEnabled = false;
      renderTab();
      expect(
        screen.getByText(/Live posture data is not available/i),
      ).toBeInTheDocument();
    });

    it("renders posture card labels even in unavailable state", () => {
      mockSecurityApi.capabilities.postureEnabled = false;
      renderTab();
      expect(
        screen.getByText("Prompt Injection Protection"),
      ).toBeInTheDocument();
      expect(screen.getByText("Citation Validation")).toBeInTheDocument();
      expect(screen.getByText("Tenant Isolation")).toBeInTheDocument();
    });
  });

  describe("AI safety posture — available", () => {
    beforeEach(() => {
      mockSecurityApi.capabilities = {
        ...mockSecurityApi.capabilities,
        postureEnabled: true,
      };
      mockSecurityApi.getSecurityPosture.mockResolvedValue(POSTURE_FIXTURE);
    });

    it("renders active posture cards with correct status", async () => {
      renderTab();
      await waitFor(() => {
        const activeLabels = screen.getAllByText("Active");
        expect(activeLabels.length).toBeGreaterThan(0);
      });
    });

    it("renders inactive posture card", async () => {
      renderTab();
      await waitFor(() => {
        expect(screen.getByText("Inactive")).toBeInTheDocument();
      });
    });
  });

  describe("audit log — unavailable", () => {
    it("shows unavailable message when audit endpoint not configured", () => {
      mockSecurityApi.capabilities.auditEnabled = false;
      renderTab();
      expect(
        screen.getByText(/Audit log is not available/i),
      ).toBeInTheDocument();
    });
  });

  describe("audit log — available", () => {
    beforeEach(() => {
      mockSecurityApi.capabilities = {
        ...mockSecurityApi.capabilities,
        auditEnabled: true,
      };
      mockSecurityApi.getRecentAuditEvents.mockResolvedValue(AUDIT_FIXTURE);
    });

    it("renders recent audit events for admin", async () => {
      mockAuth.state = { ...OWNER_SESSION };
      renderTab();
      await waitFor(() => {
        expect(
          screen.getByText("Session revoked for user@example.com"),
        ).toBeInTheDocument();
      });
    });

    it("shows restricted message for member", () => {
      mockAuth.state = { ...MEMBER_SESSION };
      renderTab();
      expect(
        screen.getByText(/Audit log access is restricted/i),
      ).toBeInTheDocument();
    });

    it("does not call getRecentAuditEvents for viewer", () => {
      mockAuth.state = { ...VIEWER_SESSION };
      renderTab();
      expect(mockSecurityApi.getRecentAuditEvents).not.toHaveBeenCalled();
    });
  });
});
