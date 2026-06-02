import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChunkingProfilesSection } from "@/components/settings/ChunkingProfilesSection";
import type { SessionState } from "@/lib/auth-session";

const mockAuth = vi.hoisted(() => ({
  state: {
    status: "authenticated",
    session: null,
  } as SessionState,
}));

const mockChunkingApi = vi.hoisted(() => ({
  createChunkingProfile: vi.fn(),
  getChunkingStrategyCatalog: vi.fn(),
  listChunkingProfiles: vi.fn(),
  previewChunkingProfile: vi.fn(),
  setDefaultChunkingProfile: vi.fn(),
  updateChunkingProfile: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({ state: mockAuth.state }),
}));

vi.mock("@/lib/api/chunking-profiles", () => ({
  createChunkingProfile: (...args: unknown[]) =>
    mockChunkingApi.createChunkingProfile(...args),
  getChunkingStrategyCatalog: () =>
    mockChunkingApi.getChunkingStrategyCatalog(),
  listChunkingProfiles: () => mockChunkingApi.listChunkingProfiles(),
  previewChunkingProfile: (...args: unknown[]) =>
    mockChunkingApi.previewChunkingProfile(...args),
  setDefaultChunkingProfile: (...args: unknown[]) =>
    mockChunkingApi.setDefaultChunkingProfile(...args),
  updateChunkingProfile: (...args: unknown[]) =>
    mockChunkingApi.updateChunkingProfile(...args),
}));

function renderSection() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <ChunkingProfilesSection />
    </QueryClientProvider>,
  );
}

describe("ChunkingProfilesSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuth.state = {
      status: "authenticated",
      session: {
        userId: "user-1",
        email: "admin@example.com",
        role: "admin",
        organizationId: "org-1",
        organizationName: "Org One",
      },
    };

    mockChunkingApi.getChunkingStrategyCatalog.mockResolvedValue({
      strategies: [
        {
          name: "adaptive_hybrid",
          display_name: "Adaptive Hybrid",
          description: "Adaptive default.",
          suitable_for: ["mixed enterprise content"],
          requires_page_structure: false,
          supports_hierarchical: false,
        },
        {
          name: "page_aware",
          display_name: "Page Aware",
          description: "Preserves page boundaries.",
          suitable_for: ["pdf"],
          requires_page_structure: true,
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
          organization_id: "org-1",
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
          created_by_user_id: "user-1",
          updated_by_user_id: "user-1",
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
    mockChunkingApi.updateChunkingProfile.mockResolvedValue({
      profile_id: "profile-1",
      organization_id: "org-1",
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
      created_by_user_id: "user-1",
      updated_by_user_id: "user-1",
    });
  });

  it("shows a restricted state for non-admin roles", async () => {
    mockAuth.state = {
      status: "authenticated",
      session: {
        userId: "user-2",
        email: "member@example.com",
        role: "member",
        organizationId: "org-1",
        organizationName: "Org One",
      },
    };

    renderSection();

    expect(
      await screen.findByText("Chunking profiles restricted"),
    ).toBeInTheDocument();
    expect(mockChunkingApi.getChunkingStrategyCatalog).not.toHaveBeenCalled();
  });

  it("loads the default profile and previews safe chunk metadata", async () => {
    renderSection();

    expect(
      await screen.findByRole("heading", { name: "Chunking Profiles" }),
    ).toBeInTheDocument();
    expect(await screen.findByLabelText("Profile Name")).toHaveValue(
      "Operations Default",
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Preview profile" }),
    );

    await waitFor(() => {
      expect(mockChunkingApi.previewChunkingProfile).toHaveBeenCalledWith(
        expect.objectContaining({
          file_type: "txt",
          config: expect.objectContaining({
            strategy: "adaptive_hybrid",
            chunk_size_tokens: 700,
            chunk_overlap_tokens: 120,
          }),
        }),
      );
    });
    expect((await screen.findAllByText("page_aware")).length).toBeGreaterThan(
      0,
    );
    expect(screen.getByText("pdf_ocr_applied")).toBeInTheDocument();
    expect(screen.getByText("Handbook > Introduction")).toBeInTheDocument();
  });

  it("blocks invalid overlap values before saving", async () => {
    renderSection();

    await screen.findByLabelText("Profile Name");
    const overlapInput = screen.getByLabelText("Overlap Tokens");
    await userEvent.clear(overlapInput);
    await userEvent.type(overlapInput, "700");
    await userEvent.click(
      screen.getByRole("button", { name: "Save default profile" }),
    );

    expect(
      await screen.findByText("Overlap must be smaller than chunk size."),
    ).toBeInTheDocument();
    expect(mockChunkingApi.updateChunkingProfile).not.toHaveBeenCalled();
  });

  it("saves the existing default profile through the update path", async () => {
    renderSection();

    await screen.findByLabelText("Profile Name");
    await userEvent.click(
      screen.getByRole("button", { name: "Save default profile" }),
    );

    await waitFor(() => {
      expect(mockChunkingApi.updateChunkingProfile).toHaveBeenCalledWith(
        "profile-1",
        expect.objectContaining({
          name: "Operations Default",
          set_as_default: true,
          config: expect.objectContaining({
            strategy: "adaptive_hybrid",
            chunk_size_tokens: 700,
            chunk_overlap_tokens: 120,
          }),
        }),
      );
    });
    expect(
      await screen.findByText("Default chunking profile saved."),
    ).toBeInTheDocument();
  });
});
