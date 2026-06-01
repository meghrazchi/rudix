import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdminSecurityCenterPage } from "@/components/admin/AdminSecurityCenterPage";
import type { SessionState } from "@/lib/auth-session";
import type { AuditLogListResponse } from "@/lib/api/admin-usage";
import type {
  LoginPolicy,
  SecurityPosture,
  SecuritySession,
} from "@/lib/api/security";
import type {
  OrganizationProfile,
  OrganizationSettings,
} from "@/lib/api/organization";
import type { TeamMemberListResponse } from "@/lib/api/team";

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

const mockSecurityApi = vi.hoisted(() => ({
  getSecurityCapabilities: vi.fn(),
  getLoginPolicy: vi.fn(),
  getSecurityPosture: vi.fn(),
  getSessions: vi.fn(),
}));

const mockOrganizationApi = vi.hoisted(() => ({
  getOrganizationCapabilities: vi.fn(),
  getOrganizationSettings: vi.fn(),
  getOrganizationProfile: vi.fn(),
}));

const mockTeamApi = vi.hoisted(() => ({
  getTeamCapabilities: vi.fn(),
  listTeamMembers: vi.fn(),
}));

const mockAdminUsageApi = vi.hoisted(() => ({
  listAuditLogs: vi.fn(),
}));

const originalEnv = { ...process.env };

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/security", () => ({
  getSecurityCapabilities: () => mockSecurityApi.getSecurityCapabilities(),
  getLoginPolicy: () => mockSecurityApi.getLoginPolicy(),
  getSecurityPosture: () => mockSecurityApi.getSecurityPosture(),
  getSessions: () => mockSecurityApi.getSessions(),
}));

vi.mock("@/lib/api/organization", () => ({
  getOrganizationCapabilities: () =>
    mockOrganizationApi.getOrganizationCapabilities(),
  getOrganizationSettings: () => mockOrganizationApi.getOrganizationSettings(),
  getOrganizationProfile: () => mockOrganizationApi.getOrganizationProfile(),
}));

vi.mock("@/lib/api/team", () => ({
  getTeamCapabilities: () => mockTeamApi.getTeamCapabilities(),
  listTeamMembers: (...args: unknown[]) => mockTeamApi.listTeamMembers(...args),
}));

vi.mock("@/lib/api/admin-usage", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/admin-usage")>(
    "@/lib/api/admin-usage",
  );
  return {
    ...actual,
    listAuditLogs: (...args: unknown[]) =>
      mockAdminUsageApi.listAuditLogs(...args),
  };
});

const LOGIN_POLICY_FIXTURE: LoginPolicy = {
  domain_allowlist: [],
  session_timeout_hours: null,
  sso_required: false,
  invite_only: true,
  mfa_required: false,
};

const POSTURE_FIXTURE: SecurityPosture = {
  prompt_injection_protection: true,
  citation_validation: true,
  tenant_isolation: true,
  output_validation: false,
  tool_policy_enforced: true,
  last_audit_at: "2026-05-30T07:00:00Z",
};

const SESSIONS_FIXTURE: SecuritySession[] = [
  {
    id: "sess-1",
    device: "Macbook Pro",
    ip_address: "127.0.0.1",
    location: "Berlin",
    created_at: "2026-05-28T10:00:00Z",
    last_active_at: "2026-05-30T07:00:00Z",
    is_current: true,
  },
  {
    id: "sess-2",
    device: "iPhone",
    ip_address: "127.0.0.2",
    location: "Berlin",
    created_at: "2026-05-28T10:00:00Z",
    last_active_at: "2026-05-30T08:00:00Z",
    is_current: false,
  },
];

const ORG_SETTINGS_FIXTURE: OrganizationSettings = {
  default_member_role: "member",
  invite_only: true,
  allowed_email_domains: [],
  default_document_visibility: "private",
  default_collection: null,
  retention_days: null,
  source_download: "all",
  evaluation_access: true,
  agentic_access: true,
  mcp_access: true,
};

const ORG_PROFILE_FIXTURE: OrganizationProfile = {
  id: "org-1",
  name: "Org One",
  slug: "org-one",
  primary_domain: "example.com",
  domain_allowlist: [],
  support_email: "support@example.com",
  description: null,
  created_at: "2026-05-01T00:00:00Z",
  plan: "Enterprise",
};

const TEAM_FIXTURE: TeamMemberListResponse = {
  items: [
    {
      member_id: "m-1",
      user_id: "u-1",
      name: "Owner",
      email: "owner@example.com",
      role: "owner",
      status: "active",
      created_at: "2026-05-01T00:00:00Z",
      updated_at: "2026-05-01T00:00:00Z",
    },
    {
      member_id: "m-2",
      user_id: "u-2",
      name: "Admin",
      email: "admin@example.com",
      role: "admin",
      status: "active",
      created_at: "2026-05-01T00:00:00Z",
      updated_at: "2026-05-01T00:00:00Z",
    },
  ],
  total: 2,
  limit: 200,
  offset: 0,
};

const AUDIT_FIXTURE: AuditLogListResponse = {
  items: [
    {
      audit_log_id: "a-1",
      organization_id: "org-1",
      user_id: "u-1",
      action: "auth.login.succeeded",
      resource_type: "auth_session",
      resource_id: "u-1",
      request_id: "req-1",
      result: "success",
      severity: "info",
      ip_address: "127.0.0.1",
      session_id: "s-1",
      document_id: null,
      collection_id: null,
      metadata: {},
      created_at: "2026-05-30T07:00:00Z",
    },
  ],
  total: 1,
  limit: 100,
  offset: 0,
  range: { from: "2026-05-01", to: "2026-05-30" },
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
      <AdminSecurityCenterPage />
    </QueryClientProvider>,
  );
}

describe("AdminSecurityCenterPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();

    process.env = {
      ...originalEnv,
      NEXT_PUBLIC_SETTINGS_BILLING_URL: "https://billing.example.com",
      NEXT_PUBLIC_SETTINGS_API_KEYS_URL: "https://api.example.com/keys",
      NEXT_PUBLIC_SETTINGS_WEBHOOKS_URL: "https://api.example.com/webhooks",
      NEXT_PUBLIC_AUTH_SSO_URL: "https://sso.example.com/start",
    };

    mockSecurityApi.getSecurityCapabilities.mockReturnValue({
      sessionsEnabled: true,
      revokeSessionEnabled: true,
      revokeAllSessionsEnabled: true,
      loginPolicyEnabled: true,
      postureEnabled: true,
      auditEnabled: true,
      auditExportEnabled: true,
    });
    mockSecurityApi.getLoginPolicy.mockResolvedValue(LOGIN_POLICY_FIXTURE);
    mockSecurityApi.getSecurityPosture.mockResolvedValue(POSTURE_FIXTURE);
    mockSecurityApi.getSessions.mockResolvedValue(SESSIONS_FIXTURE);

    mockOrganizationApi.getOrganizationCapabilities.mockReturnValue({
      profileEnabled: true,
      settingsEnabled: true,
      ingestionEnabled: true,
      transferOwnershipEnabled: false,
      archiveEnabled: false,
      exportEnabled: false,
      deleteEnabled: false,
    });
    mockOrganizationApi.getOrganizationSettings.mockResolvedValue(
      ORG_SETTINGS_FIXTURE,
    );
    mockOrganizationApi.getOrganizationProfile.mockResolvedValue(
      ORG_PROFILE_FIXTURE,
    );

    mockTeamApi.getTeamCapabilities.mockReturnValue({
      listMembersEnabled: true,
      inviteEnabled: true,
      updateRoleEnabled: true,
      removeMemberEnabled: true,
    });
    mockTeamApi.listTeamMembers.mockResolvedValue(TEAM_FIXTURE);

    mockAdminUsageApi.listAuditLogs.mockResolvedValue(AUDIT_FIXTURE);
  });

  afterEach(() => {
    process.env = { ...originalEnv };
  });

  it("renders forbidden state for non-admin roles", () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "member-1",
        email: "member@example.com",
        role: "member",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token",
      },
    };

    renderPage();

    expect(screen.getByText("Security center restricted")).toBeInTheDocument();
    expect(mockAdminUsageApi.listAuditLogs).not.toHaveBeenCalled();
  });

  it("renders security sections, warnings, and deep links for admin users", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "admin-1",
        email: "admin@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token",
      },
    };

    renderPage();

    expect(
      await screen.findByRole("heading", {
        name: "Organization Security Center",
      }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("Security Posture Summary"),
    ).toBeInTheDocument();
    expect(await screen.findByText("Security Controls")).toBeInTheDocument();
    expect(
      await screen.findByText("Security Recommendations"),
    ).toBeInTheDocument();
    expect(
      (await screen.findAllByText("MFA is not required")).length,
    ).toBeGreaterThan(0);
    expect(
      await screen.findByRole("link", {
        name: /Billing and plan controls/i,
      }),
    ).toHaveAttribute("href", "https://billing.example.com");
    expect(
      await screen.findByRole("link", { name: /^API keys/i }),
    ).toHaveAttribute("href", "https://api.example.com/keys");
    expect(
      await screen.findByRole("link", { name: /^Webhooks/i }),
    ).toHaveAttribute("href", "https://api.example.com/webhooks");
    expect(
      await screen.findByRole("link", { name: /^Audit logs/i }),
    ).toHaveAttribute("href", "/admin/audit-logs");
    expect(
      await screen.findByRole("link", { name: /^Role settings/i }),
    ).toHaveAttribute("href", "/settings?tab=organization");
    expect(
      await screen.findByRole("link", { name: /^Data retention/i }),
    ).toHaveAttribute("href", "/settings?tab=organization");
  });

  it("shows forbidden state when backend permission is denied", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "admin-1",
        email: "admin@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token",
      },
    };
    mockAdminUsageApi.listAuditLogs.mockRejectedValue({ status: 403 });

    renderPage();

    expect(
      await screen.findByText("Security center unavailable"),
    ).toBeInTheDocument();
  });
});
