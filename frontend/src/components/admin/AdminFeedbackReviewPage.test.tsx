import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminFeedbackReviewPage } from "@/components/admin/AdminFeedbackReviewPage";
import type { SessionState } from "@/lib/auth-session";
import type { FeedbackReviewItemResponse } from "@/lib/api/feedback-review";

const mockState = vi.hoisted(() => ({
  authState: { status: "unauthenticated", session: null } as SessionState,
}));

const mockApi = vi.hoisted(() => ({
  listFeedbackReviewItems: vi.fn(),
  updateFeedbackReviewItem: vi.fn(),
  triageFeedback: vi.fn(),
  convertFeedbackToEvalCase: vi.fn(),
  redactFeedbackDiagnostics: vi.fn(),
}));

const mockEvalApi = vi.hoisted(() => ({
  listEvaluationSets: vi.fn(),
}));

vi.mock("@/lib/use-auth-session", () => ({
  useAuthSession: () => ({
    state: mockState.authState,
    setAuthenticatedSession: vi.fn(),
    signOut: vi.fn(),
  }),
}));

vi.mock("@/lib/api/feedback-review", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/api/feedback-review")>();
  return {
    ...actual,
    listFeedbackReviewItems: (params?: unknown) =>
      mockApi.listFeedbackReviewItems(params),
    updateFeedbackReviewItem: (reviewId: string, payload: unknown) =>
      mockApi.updateFeedbackReviewItem(reviewId, payload),
    triageFeedback: (feedbackId: string, payload: unknown) =>
      mockApi.triageFeedback(feedbackId, payload),
    convertFeedbackToEvalCase: (reviewId: string, payload: unknown) =>
      mockApi.convertFeedbackToEvalCase(reviewId, payload),
    redactFeedbackDiagnostics: (feedbackId: string) =>
      mockApi.redactFeedbackDiagnostics(feedbackId),
  };
});

vi.mock("@/lib/api/evaluations", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/evaluations")>();
  return {
    ...actual,
    listEvaluationSets: (params?: unknown) =>
      mockEvalApi.listEvaluationSets(params),
  };
});

vi.mock("@/lib/use-overlay-focus", () => ({
  useOverlayFocus: vi.fn(),
}));

const EMPTY_RESPONSE = { items: [], total: 0, limit: 20, offset: 0 };

const SAMPLE_ITEM: FeedbackReviewItemResponse = {
  review_id: "rev-1",
  feedback_id: "fb-1",
  organization_id: "org-1",
  status: "new",
  severity: "high",
  reviewer_id: null,
  reviewer_notes: null,
  linked_eval_question_id: null,
  linked_document_id: null,
  resolved_at: null,
  created_at: "2026-06-01T10:00:00Z",
  updated_at: "2026-06-01T10:00:00Z",
  feedback: {
    feedback_id: "fb-1",
    message_id: "msg-1",
    submitter_user_id: "user-1",
    rating: "down",
    reason: "wrong_citation",
    comment: "Citation is wrong.",
    // F303 fields
    category: "bad_citation",
    question_text: "What is the capital of France?",
    answer_text: "The capital of France is London.",
    model_name: "gpt-4o",
    redacted_at: null,
    converted_to_eval_question_id: null,
    submitted_at: "2026-06-01T09:55:00Z",
  },
  message: {
    message_id: "msg-1",
    session_id: "sess-1",
    content_preview: "The capital of France is London.",
    confidence_score: 0.55,
    model_name: "gpt-4o",
    latency_ms: 890,
    created_at: "2026-06-01T09:50:00Z",
  },
};

const REDACTED_ITEM: FeedbackReviewItemResponse = {
  ...SAMPLE_ITEM,
  review_id: "rev-2",
  feedback: {
    ...SAMPLE_ITEM.feedback!,
    feedback_id: "fb-2",
    question_text: null,
    answer_text: null,
    redacted_at: "2026-06-02T10:00:00Z",
  },
};

const CONVERTED_ITEM: FeedbackReviewItemResponse = {
  ...SAMPLE_ITEM,
  review_id: "rev-3",
  status: "eval_created",
  feedback: {
    ...SAMPLE_ITEM.feedback!,
    feedback_id: "fb-3",
    converted_to_eval_question_id: "eval-q-1",
  },
};

function adminSession() {
  return {
    status: "authenticated" as const,
    session: {
      userId: "u-1",
      email: "admin@example.com",
      role: "admin" as const,
      organizationId: "org-1",
      organizationName: "Org One",
      accessToken: "token-1",
    },
  };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AdminFeedbackReviewPage />
    </QueryClientProvider>,
  );
}

describe("AdminFeedbackReviewPage", () => {
  beforeEach(() => {
    mockApi.listFeedbackReviewItems.mockReset();
    mockApi.updateFeedbackReviewItem.mockReset();
    mockApi.triageFeedback.mockReset();
    mockApi.convertFeedbackToEvalCase.mockReset();
    mockApi.redactFeedbackDiagnostics.mockReset();
    mockEvalApi.listEvaluationSets.mockReset();
    mockApi.listFeedbackReviewItems.mockResolvedValue(EMPTY_RESPONSE);
    mockEvalApi.listEvaluationSets.mockResolvedValue({ items: [], total: 0 });
  });

  it("shows forbidden state for non-admin users", async () => {
    mockState.authState = {
      status: "authenticated",
      session: {
        userId: "u-2",
        email: "member@example.com",
        role: "member",
        organizationId: "org-1",
        organizationName: "Org One",
        accessToken: "token-2",
      },
    };

    renderPage();
    expect(
      await screen.findByText("Feedback review queue restricted"),
    ).toBeInTheDocument();
    expect(mockApi.listFeedbackReviewItems).not.toHaveBeenCalled();
  });

  it("renders page header and filter controls for admin", async () => {
    mockState.authState = adminSession();
    renderPage();

    expect(
      await screen.findByText("Feedback review queue"),
    ).toBeInTheDocument();
    expect(screen.getByText("Export CSV")).toBeInTheDocument();
    expect(screen.getByText("Apply")).toBeInTheDocument();
    expect(screen.getByText("Clear")).toBeInTheDocument();
  });

  it("shows empty state when no items match", async () => {
    mockState.authState = adminSession();
    mockApi.listFeedbackReviewItems.mockResolvedValue(EMPTY_RESPONSE);

    renderPage();
    expect(
      await screen.findByText("No feedback items match the current filters."),
    ).toBeInTheDocument();
  });

  it("renders feedback items with category column", async () => {
    mockState.authState = adminSession();
    mockApi.listFeedbackReviewItems.mockResolvedValue({
      items: [SAMPLE_ITEM],
      total: 1,
      limit: 20,
      offset: 0,
    });

    renderPage();
    expect(await screen.findByText("Thumbs down")).toBeInTheDocument();
    // F303: category column shows bad citation
    expect(await screen.findByText("bad citation")).toBeInTheDocument();
    expect(await screen.findByText(/new/i)).toBeInTheDocument();
    // Question text is shown in the preview column
    expect(
      await screen.findByText(/What is the capital of France/),
    ).toBeInTheDocument();
  });

  it("shows stat cards with correct counts", async () => {
    mockState.authState = adminSession();
    const highNewItem = {
      ...SAMPLE_ITEM,
      review_id: "rev-1",
      status: "new" as const,
      severity: "high" as const,
    };
    const fixedItem = {
      ...SAMPLE_ITEM,
      review_id: "rev-2",
      status: "fixed" as const,
      severity: "low" as const,
    };
    mockApi.listFeedbackReviewItems.mockResolvedValue({
      items: [highNewItem, fixedItem],
      total: 2,
      limit: 20,
      offset: 0,
    });

    renderPage();
    const openItems = await screen.findByText("Open items (page)");
    expect(openItems).toBeInTheDocument();
    const highSev = await screen.findByText("High severity (page)");
    expect(highSev).toBeInTheDocument();
  });

  it("opens detail panel with category and question/answer text", async () => {
    mockState.authState = adminSession();
    mockApi.listFeedbackReviewItems.mockResolvedValue({
      items: [SAMPLE_ITEM],
      total: 1,
      limit: 20,
      offset: 0,
    });

    renderPage();
    const reviewBtn = await screen.findByRole("button", { name: "Review" });
    fireEvent.click(reviewBtn);

    // F303: category shown in detail panel
    expect(await screen.findByText("Category")).toBeInTheDocument();
    expect(await screen.findByText("bad citation")).toBeInTheDocument();

    // F303: captured question text shown
    expect(
      await screen.findByText("Captured question"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("What is the capital of France?"),
    ).toBeInTheDocument();

    // F303: captured answer text shown
    expect(
      await screen.findByText("Captured answer"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("The capital of France is London."),
    ).toBeInTheDocument();

    // F303: model name shown
    expect(screen.getByText("gpt-4o")).toBeInTheDocument();

    // F303: "Convert to eval case" and "Redact diagnostics" buttons
    expect(
      screen.getByRole("button", { name: "Convert to eval case" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Redact diagnostics" }),
    ).toBeInTheDocument();
  });

  it("hides redact button when already redacted", async () => {
    mockState.authState = adminSession();
    mockApi.listFeedbackReviewItems.mockResolvedValue({
      items: [REDACTED_ITEM],
      total: 1,
      limit: 20,
      offset: 0,
    });

    renderPage();
    const reviewBtn = await screen.findByRole("button", { name: "Review" });
    fireEvent.click(reviewBtn);

    expect(
      screen.queryByRole("button", { name: "Redact diagnostics" }),
    ).not.toBeInTheDocument();
    // Should show redacted-at message
    expect(await screen.findByText(/Diagnostics redacted on/)).toBeInTheDocument();
  });

  it("hides convert button when already converted", async () => {
    mockState.authState = adminSession();
    mockApi.listFeedbackReviewItems.mockResolvedValue({
      items: [CONVERTED_ITEM],
      total: 1,
      limit: 20,
      offset: 0,
    });

    renderPage();
    const reviewBtn = await screen.findByRole("button", { name: "Review" });
    fireEvent.click(reviewBtn);

    expect(
      screen.queryByRole("button", { name: "Convert to eval case" }),
    ).not.toBeInTheDocument();
    // Should show converted message
    expect(
      await screen.findByText(/Converted to eval case/),
    ).toBeInTheDocument();
  });

  it("opens ConvertToEvalModal when convert button is clicked", async () => {
    mockState.authState = adminSession();
    mockApi.listFeedbackReviewItems.mockResolvedValue({
      items: [SAMPLE_ITEM],
      total: 1,
      limit: 20,
      offset: 0,
    });
    mockEvalApi.listEvaluationSets.mockResolvedValue({
      items: [
        { evaluation_set_id: "set-1", name: "My Dataset", status: "draft" },
      ],
      total: 1,
    });

    renderPage();
    const reviewBtn = await screen.findByRole("button", { name: "Review" });
    fireEvent.click(reviewBtn);

    const convertBtn = await screen.findByRole("button", {
      name: "Convert to eval case",
    });
    fireEvent.click(convertBtn);

    expect(
      await screen.findByText("Convert to evaluation case"),
    ).toBeInTheDocument();
    expect(await screen.findByText("My Dataset")).toBeInTheDocument();
  });

  it("calls convertFeedbackToEvalCase when modal Convert is submitted", async () => {
    mockState.authState = adminSession();
    mockApi.listFeedbackReviewItems.mockResolvedValue({
      items: [SAMPLE_ITEM],
      total: 1,
      limit: 20,
      offset: 0,
    });
    mockEvalApi.listEvaluationSets.mockResolvedValue({
      items: [
        { evaluation_set_id: "set-1", name: "My Dataset", status: "draft" },
      ],
      total: 1,
    });
    mockApi.convertFeedbackToEvalCase.mockResolvedValue({
      review_id: "rev-1",
      evaluation_set_id: "set-1",
      evaluation_question_id: "eq-1",
      question: "What is the capital of France?",
      already_existed: false,
    });

    renderPage();
    const reviewBtn = await screen.findByRole("button", { name: "Review" });
    fireEvent.click(reviewBtn);

    const convertBtn = await screen.findByRole("button", {
      name: "Convert to eval case",
    });
    fireEvent.click(convertBtn);

    // Select the evaluation set
    const setSelect = await screen.findByRole("combobox", {
      name: /evaluation dataset/i,
    });
    fireEvent.change(setSelect, { target: { value: "set-1" } });

    const submitBtn = screen.getByRole("button", { name: "Convert" });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(mockApi.convertFeedbackToEvalCase).toHaveBeenCalledWith(
        "rev-1",
        expect.objectContaining({ evaluation_set_id: "set-1" }),
      );
    });
  });

  it("calls redactFeedbackDiagnostics when redact button is clicked", async () => {
    mockState.authState = adminSession();
    mockApi.listFeedbackReviewItems.mockResolvedValue({
      items: [SAMPLE_ITEM],
      total: 1,
      limit: 20,
      offset: 0,
    });
    mockApi.redactFeedbackDiagnostics.mockResolvedValue({
      ...SAMPLE_ITEM,
      feedback: { ...SAMPLE_ITEM.feedback!, redacted_at: "2026-06-02T00:00:00Z" },
    });

    renderPage();
    const reviewBtn = await screen.findByRole("button", { name: "Review" });
    fireEvent.click(reviewBtn);

    const redactBtn = await screen.findByRole("button", {
      name: "Redact diagnostics",
    });
    fireEvent.click(redactBtn);

    await waitFor(() => {
      expect(mockApi.redactFeedbackDiagnostics).toHaveBeenCalledWith("fb-1");
    });
  });

  it("calls updateFeedbackReviewItem when Save changes is clicked", async () => {
    mockState.authState = adminSession();
    const updatedItem: FeedbackReviewItemResponse = {
      ...SAMPLE_ITEM,
      status: "fixed",
      resolved_at: "2026-06-01T11:00:00Z",
    };
    mockApi.listFeedbackReviewItems.mockResolvedValue({
      items: [SAMPLE_ITEM],
      total: 1,
      limit: 20,
      offset: 0,
    });
    mockApi.updateFeedbackReviewItem.mockResolvedValue(updatedItem);

    renderPage();
    const reviewBtn = await screen.findByRole("button", { name: "Review" });
    fireEvent.click(reviewBtn);

    const statusSelect = await screen.findByDisplayValue("New");
    fireEvent.change(statusSelect, { target: { value: "fixed" } });

    const saveBtn = screen.getByRole("button", { name: "Save changes" });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(mockApi.updateFeedbackReviewItem).toHaveBeenCalledWith(
        "rev-1",
        expect.objectContaining({ status: "fixed" }),
      );
    });
  });

  it("requests items with filter params when filters are applied", async () => {
    mockState.authState = adminSession();
    mockApi.listFeedbackReviewItems.mockResolvedValue(EMPTY_RESPONSE);

    renderPage();
    await screen.findByText("No feedback items match the current filters.");

    const statusSelect = screen.getByDisplayValue("All statuses");
    fireEvent.change(statusSelect, { target: { value: "triaged" } });

    const applyBtn = screen.getByRole("button", { name: "Apply" });
    fireEvent.click(applyBtn);

    await waitFor(() => {
      const calls = mockApi.listFeedbackReviewItems.mock.calls;
      const lastCall = calls[calls.length - 1][0];
      expect(lastCall).toMatchObject({ status: "triaged" });
    });
  });
});
