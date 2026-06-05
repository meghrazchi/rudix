import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PromptTemplatesSection } from "@/components/settings/PromptTemplatesSection";
import type { SessionState } from "@/lib/auth-session";

const mockAuth = vi.hoisted(() => ({
  state: {
    status: "authenticated",
    session: null,
  } as SessionState,
}));

const mockPromptTemplatesApi = vi.hoisted(() => ({
  createPromptTemplateDraft: vi.fn(),
  getPromptTemplate: vi.fn(),
  listPromptTemplateEvalResults: vi.fn(),
  listPromptTemplates: vi.fn(),
  previewPromptTemplate: vi.fn(),
  publishPromptTemplateVersion: vi.fn(),
  rollbackPromptTemplate: vi.fn(),
  submitPromptTemplateVersionForReview: vi.fn(),
  updatePromptTemplateVersion: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({ state: mockAuth.state }),
}));

vi.mock("@/lib/api/prompt-templates", () => ({
  createPromptTemplateDraft: (...args: unknown[]) =>
    mockPromptTemplatesApi.createPromptTemplateDraft(...args),
  getPromptTemplate: (...args: unknown[]) =>
    mockPromptTemplatesApi.getPromptTemplate(...args),
  listPromptTemplateEvalResults: (...args: unknown[]) =>
    mockPromptTemplatesApi.listPromptTemplateEvalResults(...args),
  listPromptTemplates: (...args: unknown[]) =>
    mockPromptTemplatesApi.listPromptTemplates(...args),
  previewPromptTemplate: (...args: unknown[]) =>
    mockPromptTemplatesApi.previewPromptTemplate(...args),
  publishPromptTemplateVersion: (...args: unknown[]) =>
    mockPromptTemplatesApi.publishPromptTemplateVersion(...args),
  rollbackPromptTemplate: (...args: unknown[]) =>
    mockPromptTemplatesApi.rollbackPromptTemplate(...args),
  submitPromptTemplateVersionForReview: (...args: unknown[]) =>
    mockPromptTemplatesApi.submitPromptTemplateVersionForReview(...args),
  updatePromptTemplateVersion: (...args: unknown[]) =>
    mockPromptTemplatesApi.updatePromptTemplateVersion(...args),
}));

const ADMIN_SESSION: SessionState = {
  status: "authenticated",
  session: {
    userId: "user-1",
    email: "admin@example.com",
    role: "admin",
    organizationId: "org-1",
    organizationName: "Org One",
  },
};

const MEMBER_SESSION: SessionState = {
  status: "authenticated",
  session: {
    userId: "user-2",
    email: "member@example.com",
    role: "member",
    organizationId: "org-1",
    organizationName: "Org One",
  },
};

const TEMPLATE = {
  prompt_template_id: "00000000-0000-0000-0000-000000000101",
  organization_id: "00000000-0000-0000-0000-000000000001",
  template_key: "answer_generation",
  name: "Answer Generation",
  description: "Generates grounded answers.",
  category: "rag",
  latest_version_number: 1,
  active_version_number: 1,
  active_version_id: "00000000-0000-0000-0000-000000000201",
  active_state: "published",
  active_published_at: "2026-06-01T08:00:00Z",
  eval_run_count: 1,
  created_by_id: null,
  updated_by_id: null,
  created_at: "2026-06-01T08:00:00Z",
  updated_at: "2026-06-01T08:00:00Z",
} as const;

const PUBLISHED_VERSION = {
  version_id: "00000000-0000-0000-0000-000000000201",
  prompt_template_id: TEMPLATE.prompt_template_id,
  template_key: "answer_generation",
  version_number: 1,
  state: "published",
  is_active: true,
  content: "Answer with {{ question }}.",
  variables: [{ name: "question", required: true }],
  variable_schema: {
    type: "object",
    required: ["question"],
    properties: { question: { type: "string" } },
  },
  preview_context: { question: "What is Rudix?" },
  change_note: "System default",
  source_version_number: null,
  created_by_id: null,
  reviewed_by_id: null,
  published_by_id: null,
  reviewed_at: null,
  published_at: "2026-06-01T08:00:00Z",
  created_at: "2026-06-01T08:00:00Z",
  updated_at: "2026-06-01T08:00:00Z",
} as const;

const DRAFT_VERSION = {
  ...PUBLISHED_VERSION,
  version_id: "00000000-0000-0000-0000-000000000202",
  version_number: 2,
  state: "draft",
  is_active: false,
  change_note: "Draft update",
  source_version_number: 1,
  published_at: null,
} as const;

const EVAL_RESULTS = {
  prompt_template_id: TEMPLATE.prompt_template_id,
  template_key: "answer_generation",
  version_number: 1,
  items: [
    {
      evaluation_run_id: "00000000-0000-0000-0000-000000000301",
      evaluation_set_id: "00000000-0000-0000-0000-000000000401",
      run_name: "Regression run",
      status: "completed",
      summary: { overall_score: 0.92 },
      created_at: "2026-06-01T09:00:00Z",
      updated_at: "2026-06-01T09:05:00Z",
      started_at: "2026-06-01T09:00:00Z",
      completed_at: "2026-06-01T09:05:00Z",
    },
  ],
  total: 1,
  limit: 20,
  offset: 0,
} as const;

type PromptVersionFixture = typeof PUBLISHED_VERSION | typeof DRAFT_VERSION;

function promptDetail(versions: PromptVersionFixture[] = [PUBLISHED_VERSION]) {
  return {
    template: TEMPLATE,
    active_version: PUBLISHED_VERSION,
    versions: {
      prompt_template_id: TEMPLATE.prompt_template_id,
      template_key: "answer_generation",
      items: versions,
      total: versions.length,
    },
    eval_results: EVAL_RESULTS,
  };
}

function renderSection() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <PromptTemplatesSection />
    </QueryClientProvider>,
  );
}

describe("PromptTemplatesSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuth.state = { ...ADMIN_SESSION };
    mockPromptTemplatesApi.listPromptTemplates.mockResolvedValue({
      items: [TEMPLATE],
      total: 1,
      limit: 50,
      offset: 0,
    });
    mockPromptTemplatesApi.getPromptTemplate.mockResolvedValue(promptDetail());
    mockPromptTemplatesApi.listPromptTemplateEvalResults.mockResolvedValue(
      EVAL_RESULTS,
    );
    mockPromptTemplatesApi.previewPromptTemplate.mockResolvedValue({
      template_key: "answer_generation",
      version_number: 1,
      rendered_prompt: "Answer with What is Rudix?.",
      context: { question: "What is Rudix?" },
    });
  });

  it("shows a restricted state for non-admin roles", async () => {
    mockAuth.state = { ...MEMBER_SESSION };

    renderSection();

    expect(
      await screen.findByText("Prompt templates restricted"),
    ).toBeInTheDocument();
    expect(mockPromptTemplatesApi.listPromptTemplates).not.toHaveBeenCalled();
  });

  it("loads prompt detail, eval impact, and preview rendering", async () => {
    renderSection();

    expect(
      await screen.findByRole("heading", { name: "Prompt Templates" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("Regression run")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Preview" }));

    await waitFor(() => {
      expect(mockPromptTemplatesApi.previewPromptTemplate).toHaveBeenCalledWith(
        "answer_generation",
        expect.objectContaining({
          context: { question: "What is Rudix?" },
        }),
      );
    });
    expect(
      await screen.findByText("Answer with What is Rudix?."),
    ).toBeInTheDocument();
  });

  it("blocks malformed variable JSON before saving a draft", async () => {
    mockPromptTemplatesApi.getPromptTemplate.mockResolvedValue(
      promptDetail([DRAFT_VERSION, PUBLISHED_VERSION]),
    );

    renderSection();

    await userEvent.click(await screen.findByText("Version 2"));
    fireEvent.change(screen.getByLabelText("Variables"), {
      target: { value: "{invalid" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(
      await screen.findByText("Variables must be valid JSON."),
    ).toBeInTheDocument();
    expect(
      mockPromptTemplatesApi.updatePromptTemplateVersion,
    ).not.toHaveBeenCalled();
  });
});
