import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrganizationSettingsTab } from "@/components/settings/OrganizationSettingsTab";
import type { SessionState } from "@/lib/auth-session";
import type {
  OrganizationCapabilities,
  OrganizationProfile,
  OrganizationSettings,
  IngestionDefaults,
} from "@/lib/api/organization";
import type { TeamCapabilities } from "@/lib/api/team";

// ── Mock: auth session ────────────────────────────────────────────────────────

const mockAuth = vi.hoisted(() => ({
  state: {
    status: "authenticated",
    session: null,
  } as SessionState,
  signOut: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({ state: mockAuth.state, signOut: mockAuth.signOut }),
}));

// ── Mock: organization API ────────────────────────────────────────────────────

const mockOrgApi = vi.hoisted(() => ({
  capabilities: {
    profileEnabled: false,
    settingsEnabled: false,
    ingestionEnabled: false,
    transferOwnershipEnabled: false,
    archiveEnabled: false,
    exportEnabled: false,
    deleteEnabled: false,
  } as OrganizationCapabilities,
  getOrganizationProfile: vi.fn(),
  updateOrganizationProfile: vi.fn(),
  getOrganizationSettings: vi.fn(),
  updateOrganizationSettings: vi.fn(),
  getIngestionDefaults: vi.fn(),
  updateIngestionDefaults: vi.fn(),
  transferOwnership: vi.fn(),
  archiveOrganization: vi.fn(),
  exportOrganizationData: vi.fn(),
  deleteOrganization: vi.fn(),
}));

vi.mock("@/lib/api/organization", () => ({
  getOrganizationCapabilities: () => mockOrgApi.capabilities,
  getOrganizationProfile: (...args: unknown[]) =>
    mockOrgApi.getOrganizationProfile(...args),
  updateOrganizationProfile: (...args: unknown[]) =>
    mockOrgApi.updateOrganizationProfile(...args),
  getOrganizationSettings: (...args: unknown[]) =>
    mockOrgApi.getOrganizationSettings(...args),
  updateOrganizationSettings: (...args: unknown[]) =>
    mockOrgApi.updateOrganizationSettings(...args),
  getIngestionDefaults: (...args: unknown[]) =>
    mockOrgApi.getIngestionDefaults(...args),
  updateIngestionDefaults: (...args: unknown[]) =>
    mockOrgApi.updateIngestionDefaults(...args),
  transferOwnership: (...args: unknown[]) =>
    mockOrgApi.transferOwnership(...args),
  archiveOrganization: (...args: unknown[]) =>
    mockOrgApi.archiveOrganization(...args),
  exportOrganizationData: (...args: unknown[]) =>
    mockOrgApi.exportOrganizationData(...args),
  deleteOrganization: (...args: unknown[]) =>
    mockOrgApi.deleteOrganization(...args),
  isOrganizationEndpointUnavailableError: () => false,
}));

// ── Mock: team API ────────────────────────────────────────────────────────────

const mockTeamApi = vi.hoisted(() => ({
  capabilities: {
    listMembersEnabled: false,
    inviteEnabled: false,
    updateRoleEnabled: false,
    removeMemberEnabled: false,
  } as TeamCapabilities,
  listTeamMembers: vi.fn(),
  inviteTeamMember: vi.fn(),
  updateTeamMemberRole: vi.fn(),
  removeTeamMember: vi.fn(),
}));

const mockChunkingApi = vi.hoisted(() => ({
  getChunkingStrategyCatalog: vi.fn(),
  listChunkingProfiles: vi.fn(),
  createChunkingProfile: vi.fn(),
  updateChunkingProfile: vi.fn(),
  setDefaultChunkingProfile: vi.fn(),
  previewChunkingProfile: vi.fn(),
}));

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

vi.mock("@/lib/api/chunking-profiles", () => ({
  getChunkingStrategyCatalog: () =>
    mockChunkingApi.getChunkingStrategyCatalog(),
  listChunkingProfiles: () => mockChunkingApi.listChunkingProfiles(),
  createChunkingProfile: (...args: unknown[]) =>
    mockChunkingApi.createChunkingProfile(...args),
  updateChunkingProfile: (...args: unknown[]) =>
    mockChunkingApi.updateChunkingProfile(...args),
  setDefaultChunkingProfile: (...args: unknown[]) =>
    mockChunkingApi.setDefaultChunkingProfile(...args),
  previewChunkingProfile: (...args: unknown[]) =>
    mockChunkingApi.previewChunkingProfile(...args),
}));

// ── Fixtures ──────────────────────────────────────────────────────────────────

const OWNER_SESSION: SessionState = {
  status: "authenticated",
  session: {
    userId: "user-1",
    email: "owner@example.com",
    role: "owner",
    organizationId: "org-123",
    organizationName: "Acme Corp",
  },
};

const ADMIN_SESSION: SessionState = {
  status: "authenticated",
  session: {
    userId: "user-2",
    email: "admin@example.com",
    role: "admin",
    organizationId: "org-123",
    organizationName: "Acme Corp",
  },
};

const MEMBER_SESSION: SessionState = {
  status: "authenticated",
  session: {
    userId: "user-3",
    email: "member@example.com",
    role: "member",
    organizationId: "org-123",
    organizationName: "Acme Corp",
  },
};

const VIEWER_SESSION: SessionState = {
  status: "authenticated",
  session: {
    userId: "user-4",
    email: "viewer@example.com",
    role: "viewer",
    organizationId: "org-123",
    organizationName: "Acme Corp",
  },
};

const PROFILE_FIXTURE: OrganizationProfile = {
  id: "org-123",
  name: "Acme Corp",
  slug: "acme-corp",
  primary_domain: "acme.com",
  domain_allowlist: ["acme.com", "partner.org"],
  support_email: "support@acme.com",
  description: "A great company.",
  created_at: "2024-01-15T10:00:00Z",
  plan: "Pro",
};

const SETTINGS_FIXTURE: OrganizationSettings = {
  default_member_role: "member",
  invite_only: false,
  allowed_email_domains: ["acme.com"],
  default_document_visibility: "private",
  default_collection: "general",
  retention_days: 90,
  source_download: "admins",
  evaluation_access: true,
  agentic_access: false,
  mcp_access: false,
};

const INGESTION_FIXTURE: IngestionDefaults = {
  allowed_file_types: ["pdf", "docx"],
  max_upload_size_mb: 50,
  max_page_count: 500,
  duplicate_handling: "skip",
  auto_index: true,
  reindex_policy: "on_update",
  retry_policy: "once",
  default_metadata_tags: ["internal"],
};

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
      <OrganizationSettingsTab />
    </QueryClientProvider>,
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("OrganizationSettingsTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuth.state = { ...MEMBER_SESSION };
    mockOrgApi.capabilities = {
      profileEnabled: false,
      settingsEnabled: false,
      ingestionEnabled: false,
      transferOwnershipEnabled: false,
      archiveEnabled: false,
      exportEnabled: false,
      deleteEnabled: false,
    };
    mockTeamApi.capabilities = {
      listMembersEnabled: false,
      inviteEnabled: false,
      updateRoleEnabled: false,
      removeMemberEnabled: false,
    };
    mockOrgApi.getOrganizationProfile.mockResolvedValue(PROFILE_FIXTURE);
    mockOrgApi.updateOrganizationProfile.mockResolvedValue(PROFILE_FIXTURE);
    mockOrgApi.getOrganizationSettings.mockResolvedValue(SETTINGS_FIXTURE);
    mockOrgApi.updateOrganizationSettings.mockResolvedValue(SETTINGS_FIXTURE);
    mockOrgApi.getIngestionDefaults.mockResolvedValue(INGESTION_FIXTURE);
    mockOrgApi.updateIngestionDefaults.mockResolvedValue(INGESTION_FIXTURE);
    mockOrgApi.transferOwnership.mockResolvedValue(undefined);
    mockOrgApi.archiveOrganization.mockResolvedValue(undefined);
    mockOrgApi.exportOrganizationData.mockResolvedValue({
      download_url: "https://example.com/export.zip",
    });
    mockOrgApi.deleteOrganization.mockResolvedValue(undefined);
    mockChunkingApi.getChunkingStrategyCatalog.mockReset();
    mockChunkingApi.listChunkingProfiles.mockReset();
    mockChunkingApi.createChunkingProfile.mockReset();
    mockChunkingApi.updateChunkingProfile.mockReset();
    mockChunkingApi.setDefaultChunkingProfile.mockReset();
    mockChunkingApi.previewChunkingProfile.mockReset();
    mockChunkingApi.getChunkingStrategyCatalog.mockResolvedValue({
      strategies: [
        {
          name: "adaptive_hybrid",
          display_name: "Adaptive Hybrid",
          description: "Adaptive default.",
          suitable_for: ["mixed content"],
          requires_page_structure: false,
          supports_hierarchical: false,
        },
      ],
      default_config: {
        strategy: "adaptive_hybrid",
        chunk_size_tokens: 700,
        chunk_overlap_tokens: 120,
        language: null,
        min_tokens: 88,
        strategy_options: {},
      },
      feature_chunking_profiles_enabled: true,
    });
    mockChunkingApi.listChunkingProfiles.mockResolvedValue({
      profiles: [
        {
          profile_id: "profile-1",
          organization_id: "org-123",
          name: "Operations Default",
          slug: "operations-default",
          config: {
            strategy: "adaptive_hybrid",
            chunk_size_tokens: 700,
            chunk_overlap_tokens: 120,
            language: "en",
            min_tokens: 88,
            strategy_options: {},
          },
          is_default: true,
          is_system: false,
          created_at: "2026-05-20T08:00:00Z",
          updated_at: "2026-05-20T08:00:00Z",
          created_by_user_id: "user-2",
          updated_by_user_id: "user-2",
        },
      ],
      total: 1,
      has_org_default: true,
    });
    mockChunkingApi.previewChunkingProfile.mockResolvedValue({
      strategy_used: "page_aware",
      chunk_count: 6,
      min_tokens: 90,
      max_tokens: 210,
      avg_tokens: 153.5,
      total_tokens: 921,
      reason_codes: ["pdf_ocr_applied"],
      sample_chunks: [
        {
          chunk_index: 0,
          token_count: 180,
          section_path: "Handbook > Introduction",
          chunk_level: 0,
          is_parent: false,
        },
      ],
      warnings: [],
    });
  });

  // ── Organization identity ─────────────────────────────────────────────────

  it("renders organization section with session identity", async () => {
    renderTab();
    expect(
      await screen.findByRole("region", { name: "Organization section" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Acme Corp")).toBeInTheDocument();
    expect(screen.getByText("org-123")).toBeInTheDocument();
  });

  it("shows copy button for org ID and reflects copied state", async () => {
    mockAuth.state = { ...OWNER_SESSION };
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      writable: true,
      configurable: true,
    });

    renderTab();
    await screen.findByRole("region", { name: "Organization section" });

    await userEvent.click(
      screen.getByRole("button", { name: "Copy organization ID" }),
    );

    expect(writeText).toHaveBeenCalledWith("org-123");
  });

  it("shows deployment-controlled badge when profile API is not configured", () => {
    renderTab();

    const badges = screen.getAllByLabelText("Deployment-controlled");
    expect(badges.length).toBeGreaterThanOrEqual(1);
    expect(
      screen.getByText(
        /extended profile settings.*not available.*deployment-controlled/i,
      ),
    ).toBeInTheDocument();
  });

  // ── Profile form (admin, profileEnabled) ─────────────────────────────────

  it("loads and displays editable profile form for admin when profileEnabled", async () => {
    mockAuth.state = { ...ADMIN_SESSION };
    mockOrgApi.capabilities = {
      ...mockOrgApi.capabilities,
      profileEnabled: true,
    };

    renderTab();

    expect(await screen.findByLabelText("Name")).toBeInTheDocument();
    expect(screen.getByLabelText("Slug")).toBeInTheDocument();
    expect(screen.getByLabelText("Primary Domain")).toBeInTheDocument();
    expect(screen.getByLabelText("Support Email")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Save organization profile" }),
    ).toBeInTheDocument();
  });

  it("populates profile form from API response", async () => {
    mockAuth.state = { ...ADMIN_SESSION };
    mockOrgApi.capabilities = {
      ...mockOrgApi.capabilities,
      profileEnabled: true,
    };

    renderTab();

    expect(await screen.findByDisplayValue("acme-corp")).toBeInTheDocument();
    expect(screen.getByDisplayValue("acme.com")).toBeInTheDocument();
    expect(screen.getByDisplayValue("support@acme.com")).toBeInTheDocument();
  });

  it("shows slug validation error for invalid slug", async () => {
    mockAuth.state = { ...ADMIN_SESSION };
    mockOrgApi.capabilities = {
      ...mockOrgApi.capabilities,
      profileEnabled: true,
    };

    renderTab();
    const slugInput = await screen.findByLabelText("Slug");

    await userEvent.clear(slugInput);
    await userEvent.type(slugInput, "Invalid Slug!");
    await userEvent.click(
      screen.getByRole("button", { name: "Save organization profile" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /slug must be lowercase/i,
    );
    expect(mockOrgApi.updateOrganizationProfile).not.toHaveBeenCalled();
  });

  it("shows domain validation error for invalid primary domain", async () => {
    mockAuth.state = { ...ADMIN_SESSION };
    mockOrgApi.capabilities = {
      ...mockOrgApi.capabilities,
      profileEnabled: true,
    };

    renderTab();
    const domainInput = await screen.findByLabelText("Primary Domain");

    await userEvent.clear(domainInput);
    await userEvent.type(domainInput, "not-a-valid-domain");
    await userEvent.click(
      screen.getByRole("button", { name: "Save organization profile" }),
    );

    const alerts = await screen.findAllByRole("alert");
    const domainAlert = alerts.find((a) =>
      a.textContent?.toLowerCase().includes("valid domain"),
    );
    expect(domainAlert).toBeDefined();
    expect(mockOrgApi.updateOrganizationProfile).not.toHaveBeenCalled();
  });

  it("shows support email validation error for invalid email", async () => {
    mockAuth.state = { ...ADMIN_SESSION };
    mockOrgApi.capabilities = {
      ...mockOrgApi.capabilities,
      profileEnabled: true,
    };

    renderTab();
    const emailInput = await screen.findByLabelText("Support Email");

    await userEvent.clear(emailInput);
    await userEvent.type(emailInput, "not-an-email");
    await userEvent.click(
      screen.getByRole("button", { name: "Save organization profile" }),
    );

    const alerts = await screen.findAllByRole("alert");
    const emailAlert = alerts.find((a) =>
      a.textContent?.toLowerCase().includes("email"),
    );
    expect(emailAlert).toBeDefined();
    expect(mockOrgApi.updateOrganizationProfile).not.toHaveBeenCalled();
  });

  it("accepts valid slug format", async () => {
    mockAuth.state = { ...ADMIN_SESSION };
    mockOrgApi.capabilities = {
      ...mockOrgApi.capabilities,
      profileEnabled: true,
    };

    renderTab();
    const slugInput = await screen.findByLabelText("Slug");

    await userEvent.clear(slugInput);
    await userEvent.type(slugInput, "valid-slug-123");
    await userEvent.click(
      screen.getByRole("button", { name: "Save organization profile" }),
    );

    await waitFor(() => {
      expect(mockOrgApi.updateOrganizationProfile).toHaveBeenCalled();
    });
  });

  it("shows read-only profile for member/viewer when profileEnabled", async () => {
    mockAuth.state = { ...MEMBER_SESSION };
    mockOrgApi.capabilities = {
      ...mockOrgApi.capabilities,
      profileEnabled: true,
    };

    renderTab();

    await screen.findByText("acme-corp");
    expect(
      screen.queryByRole("button", { name: "Save organization profile" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Slug")).not.toBeInTheDocument();
  });

  // ── Workspace defaults ────────────────────────────────────────────────────

  it("shows workspace defaults section as unavailable when settingsEnabled is false", async () => {
    mockAuth.state = { ...ADMIN_SESSION };
    renderTab();

    await screen.findByRole("region", { name: "Workspace defaults section" });
    expect(
      screen.getByText(
        /workspace defaults are not available.*deployment-controlled/i,
      ),
    ).toBeInTheDocument();
  });

  it("shows forbidden state for workspace defaults when member/viewer", async () => {
    mockAuth.state = { ...MEMBER_SESSION };
    mockOrgApi.capabilities = {
      ...mockOrgApi.capabilities,
      settingsEnabled: true,
    };

    renderTab();

    await screen.findByRole("region", { name: "Workspace defaults section" });
    expect(
      screen.getByText("Workspace defaults restricted"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Save workspace defaults" }),
    ).not.toBeInTheDocument();
  });

  it("shows forbidden state for workspace defaults when viewer", async () => {
    mockAuth.state = { ...VIEWER_SESSION };
    mockOrgApi.capabilities = {
      ...mockOrgApi.capabilities,
      settingsEnabled: true,
    };

    renderTab();

    await screen.findByText("Workspace defaults restricted");
    expect(mockOrgApi.getOrganizationSettings).not.toHaveBeenCalled();
  });

  it("loads and shows editable workspace defaults for admin when settingsEnabled", async () => {
    mockAuth.state = { ...ADMIN_SESSION };
    mockOrgApi.capabilities = {
      ...mockOrgApi.capabilities,
      settingsEnabled: true,
    };

    renderTab();

    expect(
      await screen.findByRole("button", { name: "Save workspace defaults" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Default Member Role")).toBeInTheDocument();
    expect(screen.getByLabelText("Invite-only mode")).toBeInTheDocument();
  });

  it("saves workspace defaults successfully", async () => {
    mockAuth.state = { ...ADMIN_SESSION };
    mockOrgApi.capabilities = {
      ...mockOrgApi.capabilities,
      settingsEnabled: true,
    };

    renderTab();

    await screen.findByRole("button", { name: "Save workspace defaults" });
    await userEvent.click(
      screen.getByRole("button", { name: "Save workspace defaults" }),
    );

    await waitFor(() => {
      expect(mockOrgApi.updateOrganizationSettings).toHaveBeenCalledTimes(1);
    });
    expect(
      await screen.findByText("Workspace defaults saved."),
    ).toBeInTheDocument();
  });

  // ── Ingestion defaults ────────────────────────────────────────────────────

  it("shows ingestion defaults section as unavailable when ingestionEnabled is false", async () => {
    mockAuth.state = { ...ADMIN_SESSION };
    renderTab();

    await screen.findByRole("region", {
      name: "Document and ingestion defaults section",
    });
    expect(
      screen.getByText(
        /ingestion defaults are not available.*deployment-controlled/i,
      ),
    ).toBeInTheDocument();
  });

  it("shows forbidden state for ingestion defaults when member", async () => {
    mockAuth.state = { ...MEMBER_SESSION };
    mockOrgApi.capabilities = {
      ...mockOrgApi.capabilities,
      ingestionEnabled: true,
    };

    renderTab();

    await screen.findByText("Ingestion defaults restricted");
    expect(
      screen.queryByRole("button", { name: "Save ingestion defaults" }),
    ).not.toBeInTheDocument();
  });

  it("shows chunking profile section as restricted for member", async () => {
    mockAuth.state = { ...MEMBER_SESSION };

    renderTab();

    expect(
      await screen.findByRole("region", { name: "Chunking profiles section" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Chunking profiles restricted"),
    ).toBeInTheDocument();
  });

  it("loads chunking profile defaults for admin", async () => {
    mockAuth.state = { ...ADMIN_SESSION };

    renderTab();

    expect(
      await screen.findByRole("heading", { name: "Chunking Profiles" }),
    ).toBeInTheDocument();
    expect(await screen.findByLabelText("Profile Name")).toHaveValue(
      "Operations Default",
    );
  });

  it("loads and shows editable ingestion defaults for admin when ingestionEnabled", async () => {
    mockAuth.state = { ...ADMIN_SESSION };
    mockOrgApi.capabilities = {
      ...mockOrgApi.capabilities,
      ingestionEnabled: true,
    };

    renderTab();

    expect(
      await screen.findByRole("button", { name: "Save ingestion defaults" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Allowed File Types")).toBeInTheDocument();
    expect(screen.getByLabelText("Duplicate Handling")).toBeInTheDocument();
  });

  it("saves ingestion defaults successfully", async () => {
    mockAuth.state = { ...ADMIN_SESSION };
    mockOrgApi.capabilities = {
      ...mockOrgApi.capabilities,
      ingestionEnabled: true,
    };

    renderTab();

    await screen.findByRole("button", { name: "Save ingestion defaults" });
    await userEvent.click(
      screen.getByRole("button", { name: "Save ingestion defaults" }),
    );

    await waitFor(() => {
      expect(mockOrgApi.updateIngestionDefaults).toHaveBeenCalledTimes(1);
    });
    expect(
      await screen.findByText("Ingestion defaults saved."),
    ).toBeInTheDocument();
  });

  // ── Admin controls ────────────────────────────────────────────────────────

  it("shows admin controls link for owner/admin", async () => {
    mockAuth.state = { ...ADMIN_SESSION };
    renderTab();

    expect(
      await screen.findByRole("link", { name: "Open admin surface" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Admin controls restricted"),
    ).not.toBeInTheDocument();
  });

  it("shows forbidden state in admin controls for member/viewer", async () => {
    mockAuth.state = { ...MEMBER_SESSION };
    renderTab();

    await screen.findByText("Admin-only controls");
    expect(screen.getByText("Admin controls restricted")).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Open admin surface" }),
    ).not.toBeInTheDocument();
  });

  it("shows forbidden state in admin controls for viewer", async () => {
    mockAuth.state = { ...VIEWER_SESSION };
    renderTab();

    await screen.findByText("Admin-only controls");
    expect(screen.getByText("Admin controls restricted")).toBeInTheDocument();
  });

  // ── Danger zone ───────────────────────────────────────────────────────────

  it("does not render danger zone for non-owner roles", async () => {
    mockAuth.state = { ...ADMIN_SESSION };
    renderTab();

    await screen.findByText("Admin-only controls");
    expect(
      screen.queryByRole("region", { name: "Danger zone section" }),
    ).not.toBeInTheDocument();
  });

  it("does not render danger zone for member", async () => {
    mockAuth.state = { ...MEMBER_SESSION };
    renderTab();

    await screen.findByText("Admin-only controls");
    expect(
      screen.queryByRole("region", { name: "Danger zone section" }),
    ).not.toBeInTheDocument();
  });

  it("renders danger zone section for owner", async () => {
    mockAuth.state = { ...OWNER_SESSION };
    renderTab();

    expect(
      await screen.findByRole("region", { name: "Danger zone section" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Danger Zone")).toBeInTheDocument();
  });

  it("shows unavailable state for danger zone actions when not configured", async () => {
    mockAuth.state = { ...OWNER_SESSION };
    renderTab();

    await screen.findByRole("region", { name: "Danger zone section" });
    const unavailables = screen.getAllByText("Unavailable");
    expect(unavailables.length).toBeGreaterThanOrEqual(4);
  });

  it("shows danger zone action buttons when capabilities are enabled", async () => {
    mockAuth.state = { ...OWNER_SESSION };
    mockOrgApi.capabilities = {
      profileEnabled: false,
      settingsEnabled: false,
      ingestionEnabled: false,
      transferOwnershipEnabled: true,
      archiveEnabled: true,
      exportEnabled: true,
      deleteEnabled: true,
    };

    renderTab();

    await screen.findByRole("region", { name: "Danger zone section" });
    expect(
      screen.getByRole("button", { name: "Transfer ownership" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Archive" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Export data" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("disables transfer ownership button when target user ID is empty", async () => {
    mockAuth.state = { ...OWNER_SESSION };
    mockOrgApi.capabilities = {
      ...mockOrgApi.capabilities,
      transferOwnershipEnabled: true,
    };

    renderTab();

    await screen.findByRole("region", { name: "Danger zone section" });
    expect(
      screen.getByRole("button", { name: "Transfer ownership" }),
    ).toBeDisabled();
  });

  // ── Loading and error states ──────────────────────────────────────────────

  it("shows loading state while profile loads", async () => {
    mockAuth.state = { ...ADMIN_SESSION };
    mockOrgApi.capabilities = {
      ...mockOrgApi.capabilities,
      profileEnabled: true,
    };
    mockOrgApi.getOrganizationProfile.mockReturnValue(new Promise(() => {}));

    renderTab();

    expect(
      await screen.findByText("Loading organization profile..."),
    ).toBeInTheDocument();
  });

  it("shows error state when profile load fails", async () => {
    mockAuth.state = { ...ADMIN_SESSION };
    mockOrgApi.capabilities = {
      ...mockOrgApi.capabilities,
      profileEnabled: true,
    };
    mockOrgApi.getOrganizationProfile.mockRejectedValue(
      new Error("Something went wrong while contacting the API."),
    );

    renderTab();

    await waitFor(() => {
      expect(
        screen.getByText("Something went wrong while contacting the API."),
      ).toBeInTheDocument();
    });
  });

  it("shows loading state while workspace defaults load", async () => {
    mockAuth.state = { ...ADMIN_SESSION };
    mockOrgApi.capabilities = {
      ...mockOrgApi.capabilities,
      settingsEnabled: true,
    };
    mockOrgApi.getOrganizationSettings.mockReturnValue(new Promise(() => {}));

    renderTab();

    expect(
      await screen.findByText("Loading workspace defaults..."),
    ).toBeInTheDocument();
  });

  // ── Team management section ───────────────────────────────────────────────

  it("renders team management section", async () => {
    renderTab();

    expect(
      await screen.findByRole("region", { name: "Team management section" }),
    ).toBeInTheDocument();
  });
});
