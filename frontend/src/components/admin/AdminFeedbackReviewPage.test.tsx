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
    mockApi.listFeedbackReviewItems.mockResolvedValue(EMPTY_RESPONSE);
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

  it("renders feedback items in queue table", async () => {
    mockState.authState = adminSession();
    mockApi.listFeedbackReviewItems.mockResolvedValue({
      items: [SAMPLE_ITEM],
      total: 1,
      limit: 20,
      offset: 0,
    });

    renderPage();
    expect(await screen.findByText("Thumbs down")).toBeInTheDocument();
    expect(await screen.findByText("wrong_citation")).toBeInTheDocument();
    expect(await screen.findByText(/new/i)).toBeInTheDocument();
    expect(
      await screen.findByText(/The capital of France is London/),
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

  it("opens detail panel when Review button is clicked", async () => {
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

    expect(await screen.findByText("Original feedback")).toBeInTheDocument();
    expect(await screen.findByText("Original answer")).toBeInTheDocument();
    expect(screen.getByText("Citation is wrong.")).toBeInTheDocument();
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
