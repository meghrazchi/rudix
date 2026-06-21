import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminAIResponsePolicyPage } from "@/components/admin/AdminAIResponsePolicyPage";
import type {
  AiResponsePolicyListResponse,
  AiResponsePolicyResponse,
  PolicyEvaluationLogListResponse,
  PolicyEvaluationLogResponse,
  PolicyPreviewResponse,
} from "@/lib/api/ai-response-policy";

// ── Mocks ─────────────────────────────────────────────────────────────────────

const mockApi = vi.hoisted(() => ({
  listAiResponsePolicies: vi.fn(),
  getActiveAiResponsePolicy: vi.fn(),
  createAiResponsePolicy: vi.fn(),
  updateAiResponsePolicy: vi.fn(),
  deleteAiResponsePolicy: vi.fn(),
  activateAiResponsePolicy: vi.fn(),
  deactivateAiResponsePolicy: vi.fn(),
  previewAiResponsePolicy: vi.fn(),
  listPolicyEvaluationLogs: vi.fn(),
}));

vi.mock("@/lib/api/ai-response-policy", () => ({
  listAiResponsePolicies: (params?: unknown) =>
    mockApi.listAiResponsePolicies(params),
  getActiveAiResponsePolicy: () => mockApi.getActiveAiResponsePolicy(),
  createAiResponsePolicy: (payload: unknown) =>
    mockApi.createAiResponsePolicy(payload),
  updateAiResponsePolicy: (id: string, payload: unknown) =>
    mockApi.updateAiResponsePolicy(id, payload),
  deleteAiResponsePolicy: (id: string) => mockApi.deleteAiResponsePolicy(id),
  activateAiResponsePolicy: (id: string) =>
    mockApi.activateAiResponsePolicy(id),
  deactivateAiResponsePolicy: (id: string) =>
    mockApi.deactivateAiResponsePolicy(id),
  previewAiResponsePolicy: (payload: unknown) =>
    mockApi.previewAiResponsePolicy(payload),
  listPolicyEvaluationLogs: (params?: unknown) =>
    mockApi.listPolicyEvaluationLogs(params),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: {
      status: "authenticated",
      session: { role: "admin", userId: "user-1", organizationId: "org-1" },
    },
  }),
}));

vi.mock("@/lib/forbidden", () => ({
  isForbiddenError: () => false,
  extractRequestIdFromError: () => null,
}));

vi.mock("@/lib/api/errors", () => ({
  getApiErrorMessage: (err: unknown) =>
    err instanceof Error ? err.message : "Error",
}));

vi.mock("@/lib/api/query", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/api/query")>();
  return {
    ...real,
    invalidateAfterMutation: vi.fn().mockResolvedValue(undefined),
  };
});

// ── Helpers ───────────────────────────────────────────────────────────────────

function makePolicy(
  overrides: Partial<AiResponsePolicyResponse> = {},
): AiResponsePolicyResponse {
  return {
    policy_id: "policy-1",
    organization_id: "org-1",
    policy_name: "Safety Policy",
    description: "Test description",
    is_active: false,
    citation_mode: "recommended",
    min_confidence_threshold: null,
    no_answer_behavior: "warn",
    stale_source_behavior: "warn",
    blocked_topics: [],
    allowed_topics: null,
    min_sources_required: null,
    disclaimer_text: null,
    disclaimer_position: "prepend",
    refusal_message: null,
    created_by_id: "user-1",
    updated_by_id: null,
    created_at: "2026-06-26T10:00:00Z",
    updated_at: "2026-06-26T10:00:00Z",
    ...overrides,
  };
}

function makeList(
  items: AiResponsePolicyResponse[] = [],
): AiResponsePolicyListResponse {
  return { items, total: items.length };
}

function makeLog(
  overrides: Partial<PolicyEvaluationLogResponse> = {},
): PolicyEvaluationLogResponse {
  return {
    log_id: "log-1",
    organization_id: "org-1",
    user_id: "user-1",
    org_policy_id: "policy-1",
    collection_id: null,
    chat_session_id: "session-1",
    chat_message_id: "msg-1",
    outcome: "blocked",
    policy_source: "org",
    violated_rules: ["blocked_topic:gambling"],
    warning_flags: [],
    question_preview: "gambling strategy?",
    confidence_score: 0.9,
    citation_count: 0,
    stale_source_count: 0,
    is_preview_run: false,
    created_at: "2026-06-26T10:00:00Z",
    ...overrides,
  };
}

function makeLogList(
  items: PolicyEvaluationLogResponse[] = [],
): PolicyEvaluationLogListResponse {
  return { items, total: items.length, limit: 50, offset: 0 };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AdminAIResponsePolicyPage />
    </QueryClientProvider>,
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("AdminAIResponsePolicyPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.listAiResponsePolicies.mockResolvedValue(makeList());
    mockApi.listPolicyEvaluationLogs.mockResolvedValue(makeLogList());
  });

  it("shows empty state when no policies exist", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/no policies yet/i)).toBeInTheDocument();
    });
  });

  it("renders policy table with policy row", async () => {
    mockApi.listAiResponsePolicies.mockResolvedValue(
      makeList([makePolicy({ policy_name: "My Policy" })]),
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("My Policy")).toBeInTheDocument();
    });
  });

  it("shows active badge for active policy", async () => {
    mockApi.listAiResponsePolicies.mockResolvedValue(
      makeList([makePolicy({ is_active: true })]),
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Active")).toBeInTheDocument();
    });
  });

  it("shows inactive badge for inactive policy", async () => {
    mockApi.listAiResponsePolicies.mockResolvedValue(
      makeList([makePolicy({ is_active: false })]),
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Inactive")).toBeInTheDocument();
    });
  });

  it("shows citation mode in table", async () => {
    mockApi.listAiResponsePolicies.mockResolvedValue(
      makeList([makePolicy({ citation_mode: "required" })]),
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Required")).toBeInTheDocument();
    });
  });

  it("shows blocked topics in table", async () => {
    mockApi.listAiResponsePolicies.mockResolvedValue(
      makeList([makePolicy({ blocked_topics: ["gambling", "politics"] })]),
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/gambling/i)).toBeInTheDocument();
    });
  });

  it("opens create form on New Policy click", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/no policies yet/i)).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /new policy/i }));
    await waitFor(() => {
      expect(screen.getByText("Create Policy")).toBeInTheDocument();
    });
  });

  it("submits create form with policy_name", async () => {
    const created = makePolicy({ policy_name: "New Safety Policy" });
    mockApi.createAiResponsePolicy.mockResolvedValue(created);
    mockApi.listAiResponsePolicies
      .mockResolvedValueOnce(makeList())
      .mockResolvedValue(makeList([created]));

    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/no policies yet/i)).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /new policy/i }));
    await waitFor(() =>
      expect(screen.getByText("Create Policy")).toBeInTheDocument(),
    );

    fireEvent.change(
      screen.getByPlaceholderText(/e.g. enterprise safety policy/i),
      { target: { value: "New Safety Policy" } },
    );
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => {
      expect(mockApi.createAiResponsePolicy).toHaveBeenCalledWith(
        expect.objectContaining({ policy_name: "New Safety Policy" }),
      );
    });
  });

  it("calls activateAiResponsePolicy on Activate click", async () => {
    const policy = makePolicy({ is_active: false });
    mockApi.listAiResponsePolicies.mockResolvedValue(makeList([policy]));
    mockApi.activateAiResponsePolicy.mockResolvedValue({
      ...policy,
      is_active: true,
    });

    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Inactive")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /activate/i }));
    await waitFor(() => {
      expect(mockApi.activateAiResponsePolicy).toHaveBeenCalledWith("policy-1");
    });
  });

  it("calls deactivateAiResponsePolicy on Deactivate click", async () => {
    const policy = makePolicy({ is_active: true });
    mockApi.listAiResponsePolicies.mockResolvedValue(makeList([policy]));
    mockApi.deactivateAiResponsePolicy.mockResolvedValue({
      ...policy,
      is_active: false,
    });

    renderPage();
    await waitFor(() => expect(screen.getByText("Active")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /deactivate/i }));
    await waitFor(() => {
      expect(mockApi.deactivateAiResponsePolicy).toHaveBeenCalledWith(
        "policy-1",
      );
    });
  });

  it("shows delete button only for inactive policies", async () => {
    const activePolicy = makePolicy({ policy_id: "a", is_active: true });
    const inactivePolicy = makePolicy({ policy_id: "b", is_active: false });
    mockApi.listAiResponsePolicies.mockResolvedValue(
      makeList([activePolicy, inactivePolicy]),
    );
    renderPage();
    await waitFor(() => expect(screen.getByText("Active")).toBeInTheDocument());
    const deleteButtons = screen.getAllByRole("button", { name: /delete/i });
    expect(deleteButtons).toHaveLength(1);
  });

  it("calls deleteAiResponsePolicy on Delete click", async () => {
    const policy = makePolicy({ is_active: false });
    mockApi.listAiResponsePolicies
      .mockResolvedValueOnce(makeList([policy]))
      .mockResolvedValue(makeList());
    mockApi.deleteAiResponsePolicy.mockResolvedValue(undefined);

    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Inactive")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /delete/i }));
    await waitFor(() => {
      expect(mockApi.deleteAiResponsePolicy).toHaveBeenCalledWith("policy-1");
    });
  });

  it("opens preview panel on Test click", async () => {
    const policy = makePolicy();
    mockApi.listAiResponsePolicies.mockResolvedValue(makeList([policy]));
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Safety Policy")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /^test$/i }));
    await waitFor(() => {
      expect(screen.getByText(/test: safety policy/i)).toBeInTheDocument();
    });
  });

  it("submits preview and shows outcome", async () => {
    const policy = makePolicy();
    mockApi.listAiResponsePolicies.mockResolvedValue(makeList([policy]));
    const preview: PolicyPreviewResponse = {
      outcome: "blocked",
      policy_source: "org",
      policy_id: "policy-1",
      violated_rules: ["blocked_topic:gambling"],
      warning_flags: [],
      refusal_message: "Refused.",
      disclaimer_text: null,
      disclaimer_position: "prepend",
    };
    mockApi.previewAiResponsePolicy.mockResolvedValue(preview);

    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Safety Policy")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /^test$/i }));

    await waitFor(() =>
      expect(screen.getByText(/run preview/i)).toBeInTheDocument(),
    );
    fireEvent.change(
      screen.getByPlaceholderText(/e.g. what are the payment options/i),
      { target: { value: "gambling strategy?" } },
    );
    fireEvent.click(screen.getByRole("button", { name: /run preview/i }));

    await waitFor(() => {
      expect(screen.getByText(/blocked/i)).toBeInTheDocument();
      expect(screen.getByText(/blocked_topic:gambling/i)).toBeInTheDocument();
    });
  });

  it("switches to logs tab and shows evaluation log", async () => {
    const log = makeLog({ outcome: "warned", question_preview: "Help me!" });
    mockApi.listAiResponsePolicies.mockResolvedValue(makeList());
    mockApi.listPolicyEvaluationLogs.mockResolvedValue(makeLogList([log]));

    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/no policies yet/i)).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /decision logs/i }));

    await waitFor(() => {
      expect(screen.getByText("Help me!")).toBeInTheDocument();
      expect(screen.getByText(/warned/i)).toBeInTheDocument();
    });
  });

  it("shows empty state on logs tab when no logs exist", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/no policies yet/i)).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /decision logs/i }));

    await waitFor(() => {
      expect(
        screen.getByText(/no policy decisions logged/i),
      ).toBeInTheDocument();
    });
  });
});
